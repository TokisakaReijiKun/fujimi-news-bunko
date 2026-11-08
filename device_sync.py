"""Opt-in LAN pairing and library transport, separate from the local management app."""
from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit

import qrcode
from flask import Flask, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException, Unauthorized
from werkzeug.serving import ThreadedWSGIServer, WSGIRequestHandler
from tailscale_link import TailscaleError, tailscale_ipv4
from device_speech import DeviceSpeech, DeviceSpeechError


PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                         ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
NAME = '富士見新聞文庫'


def private_ipv4(value):
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and any(address in network for network in PRIVATE_NETWORKS)
    except ValueError:
        return False


def loopback(value):
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _windows_private_address():
    """VPN routes may win UDP selection; use Windows adapter metadata instead."""
    script = """
$ErrorActionPreference = 'Stop'
ConvertTo-Json -Depth 3 -Compress -InputObject @(Get-NetIPConfiguration | ForEach-Object {
    [PSCustomObject]@{
        hardware = $_.NetAdapter.HardwareInterface
        up = ($_.NetAdapter.InterfaceOperationalStatus -eq 1)
        metric = $_.NetIPv4Interface.InterfaceMetric
        addresses = @($_.IPv4Address.IPAddress)
        gateways = @($_.IPv4DefaultGateway.NextHop)
    }
})
"""
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            check=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        adapters = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    physical = [adapter for adapter in adapters if adapter.get('hardware') and adapter.get('up')]
    physical.sort(key=lambda adapter: (not any(adapter.get('gateways') or []),
                                      adapter.get('metric') or 65535))
    return next((address for adapter in physical for address in adapter.get('addresses', [])
                 if address and private_ipv4(address)), None)


def recommended_private_address():
    """Prefer a physical Windows LAN; elsewhere use the route without sending data."""
    if os.name == 'nt':
        return _windows_private_address()
    candidates = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(('192.0.2.1', 9))
            candidates.append(route.getsockname()[0])
    except OSError:
        pass
    try:
        candidates.extend(item[4][0] for item in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM))
    except OSError:
        pass
    return next((address for address in candidates if private_ipv4(address)), None)


def make_sync_server(host, port, app):
    class ExclusiveServer(ThreadedWSGIServer):
        allow_reuse_address = False

        def server_bind(self):
            if os.name == 'nt':
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    return ExclusiveServer(host, port, app, handler=WSGIRequestHandler)


def same_origin():
    origin = request.headers.get('Origin')
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return False
    return not origin or origin == request.host_url.rstrip('/')


class DeviceSync:
    def __init__(self, library=None, *, port=8429, connector=None, speech=None):
        self.library = library
        self.speech = DeviceSpeech(library, speech)
        self.port = port
        self.connector = connector
        self.lock = threading.RLock()
        self.transfer_lock = threading.Lock()
        self.server = None
        self.thread = None
        self.enabled = False
        self.host = ''
        self.code = ''
        self.devices = {}
        self.failed_attempts = {}
        self.error = ''
        self.connecting = False
        self.generation = 0
        self.network = 'lan'
        self.tailscale_status = 'unavailable'
        self.login_url = ''
        self.app = Flask('fujimi_device_sync', static_folder=None)
        self.app.json.ensure_ascii = False
        self.app.config['MAX_CONTENT_LENGTH'] = MAX_BUNDLE_BYTES
        self._register_lan()

    def state(self):
        with self.lock:
            devices = [dict(value) for value in self.devices.values()]
            status = 'paired' if devices else 'waiting'
            detail = '已配对设备，可以同步文库。' if devices else '等待 Android 扫码或输入地址和配对码。'
            if self.enabled and self.network == 'tailscale':
                detail = '已通过 Tailscale 连接，请确认手机已登录并连接同一 Tailscale 网络。' + detail
            if not self.enabled:
                status = 'connecting' if self.connecting else ('error' if self.error else 'disabled')
                detail = ('正在检查同步网络并连接 Tailscale…' if self.connecting
                          else self.error or '文庫互联已关闭。')
            return {'enabled': self.enabled, 'url': f'http://{self.host}:{self.port}' if self.enabled else '',
                    'pairing_code': self.code, 'paired_devices': devices, 'status': status,
                    'detail': detail, 'qr_url': '/api/settings/device-sync/qr' if self.enabled else '',
                    'sync_available': self.enabled and self.library is not None,
                    'network': self.network, 'tailscale_status': self.tailscale_status,
                    'login_url': self.login_url, **self.speech.capabilities()}

    def enable(self):
        with self.lock:
            if self.enabled:
                return self.state()
            if self.connecting:
                return self.state()
            self.error = ''
            self.login_url = ''
            self.connecting = True
            self.generation += 1
            generation = self.generation

        def cancelled():
            with self.lock:
                return self.generation != generation

        # CLI and adapter queries must not hold the settings/status/cancel lock.
        network, tailscale_status = 'lan', 'unavailable'
        try:
            connection = self.connector.connect(cancelled=cancelled) if self.connector is not None else None
            if cancelled():
                return self.state()
            if connection is not None and connection.status != 'unavailable':
                network, tailscale_status = 'tailscale', connection.status
                host = connection.host
                if tailscale_status != 'ready' or not tailscale_ipv4(host):
                    raise TailscaleError('Tailscale 尚未提供有效的本机 IPv4 地址，请连接成功后重试。')
            else:
                host = recommended_private_address()
                if not host or not private_ipv4(host):
                    raise ValueError('没有可用的局域网 IPv4 地址，请连接与手机相同的 Wi-Fi 后重试。')
        except ValueError as error:
            with self.lock:
                if self.generation != generation:
                    return self.state()
                self.connecting = False
                self.error = str(error)
                self.network = 'tailscale' if isinstance(error, TailscaleError) else network
                self.tailscale_status = error.status if isinstance(error, TailscaleError) else tailscale_status
                self.login_url = error.login_url if isinstance(error, TailscaleError) else ''
            raise
        with self.lock:
            if self.generation != generation:
                return self.state()
            self.connecting = False
            self.network, self.tailscale_status = network, tailscale_status
            try:
                server = make_sync_server(host, self.port, self.app)
            except (OSError, SystemExit):
                self.error = f'无法开启同步端口 {self.port}，请检查端口占用或网络连接。'
                raise ValueError(self.error) from None
            self.server = server
            self.host = host
            self.code = f'{secrets.randbelow(1000000):06d}'
            self.devices.clear()
            self.failed_attempts.clear()
            self.enabled = True
            self.thread = threading.Thread(target=server.serve_forever, name='fujimi-device-sync', daemon=True)
            self.thread.start()
            return self.state()

    def shutdown(self):
        with self.lock:
            server, thread = self.server, self.thread
            self.server = self.thread = None
            self.enabled = False
            self.connecting = False
            self.generation += 1
            self.login_url = ''
            self.network = self.tailscale_status = ''
            self.host = self.code = self.error = ''
            self.devices.clear()
            self.failed_attempts.clear()
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)

    def register_control(self, app):
        def permitted():
            host = urlsplit(request.host_url).hostname or ''
            return loopback(request.remote_addr or '') and (host == 'localhost' or loopback(host)) and same_origin()

        @app.route('/api/settings/device-sync', methods=['GET', 'PUT'])
        def device_sync_settings():
            if not permitted():
                return jsonify(detail='同步设置仅允许本机页面访问。'), 403
            if request.method == 'PUT':
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict) or type(payload.get('enabled')) is not bool:
                    return jsonify(detail='enabled 必须为布尔值。'), 400
                if payload['enabled']:
                    try:
                        self.enable()
                    except ValueError:
                        return jsonify(self.state()), 503
                else:
                    self.shutdown()
            response = jsonify(self.state())
            response.headers['Cache-Control'] = 'no-store'
            return response

        @app.get('/api/settings/device-sync/qr')
        def device_sync_qr():
            if not permitted():
                return jsonify(detail='配对二维码仅允许本机页面访问。'), 403
            state = self.state()
            if not state['enabled']:
                return jsonify(detail='请先开启局域网同步。'), 409
            payload = {'type': 'fujimi-sync', 'version': 2, 'url': state['url'], 'code': state['pairing_code']}
            output = io.BytesIO()
            qrcode.make(json.dumps(payload, ensure_ascii=False, separators=(',', ':'))).save(output, format='PNG')
            output.seek(0)
            response = send_file(output, mimetype='image/png')
            response.headers['Cache-Control'] = 'no-store'
            return response

        app.extensions['device_sync'] = self

    def _register_lan(self):
        def require_current_pairing():
            with self.lock:
                token = request.headers.get('Authorization', '')
                token = token[7:] if token.startswith('Bearer ') else ''
                if not self.enabled or token not in self.devices:
                    raise Unauthorized('配对已失效，请重新配对后再同步。')

        @self.app.before_request
        def lan_boundary():
            with self.lock:
                if not self.enabled:
                    return jsonify(detail='局域网同步已关闭。'), 503
                if request.host != f'{self.host}:{self.port}' or not same_origin():
                    return jsonify(detail='无效的同步来源。'), 403
                remote = request.remote_addr or ''
                if not (private_ipv4(remote) or loopback(remote)
                        or (self.network == 'tailscale' and tailscale_ipv4(self.host) and tailscale_ipv4(remote))):
                    return jsonify(detail='同步仅限本地或已连接的 Tailscale 网络。'), 403
                if request.endpoint not in ('sync_info', 'sync_pair') and request.endpoint is not None:
                    token = request.headers.get('Authorization', '')
                    token = token[7:] if token.startswith('Bearer ') else ''
                    device = self.devices.get(token)
                    if not device:
                        return jsonify(detail='请重新配对后再同步。'), 401
                    g.sync_device = dict(device)
                    g.sync_speech_owner = hashlib.sha256(token.encode('ascii')).hexdigest()

        @self.app.after_request
        def no_cache(response):
            response.headers['Cache-Control'] = 'no-store'
            return response

        @self.app.errorhandler(Exception)
        def sync_error(error):
            if isinstance(error, DeviceSpeechError):
                return jsonify(detail=error.detail, code=error.code), error.status
            if isinstance(error, HTTPException):
                return jsonify(detail='同步请求过大。' if error.code == 413 else error.description), error.code
            if isinstance(error, ValueError):
                return jsonify(detail=str(error)), 400
            self.app.logger.exception('Library synchronization failed')
            return jsonify(detail='文库同步失败，请检查文库文件与可用空间后重试。'), 500

        @self.app.get('/api/sync/v2/info')
        def sync_info():
            return jsonify(protocol=2, name=NAME, pairing_required=True,
                           sync_available=self.library is not None, **self.speech.capabilities())

        @self.app.post('/api/sync/v2/pair')
        def sync_pair():
            request.max_content_length = 4096
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify(detail='配对信息格式不正确。'), 400
            with self.lock:
                address, current = request.remote_addr, time.monotonic()
                self.failed_attempts = {key: [stamp for stamp in values if current - stamp < 60]
                                        for key, values in self.failed_attempts.items()
                                        if values and current - values[-1] < 60}
                attempts = self.failed_attempts.setdefault(address, [])
                if len(attempts) >= 5:
                    return jsonify(detail='配对码错误次数过多，请一分钟后重试。'), 429, {'Retry-After': '60'}
                code = payload.get('code')
                if not isinstance(code, str) or not code.isascii() or not secrets.compare_digest(code, self.code):
                    attempts.append(current)
                    return jsonify(detail='配对码不正确，请查看 PC 上的六位配对码。'), 401
                device_id = payload.get('device_id')
                name = payload.get('device_name', 'Android')
                if not isinstance(device_id, str) or not 1 <= len(device_id.strip()) <= 128:
                    return jsonify(detail='设备标识不正确。'), 400
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
                    return jsonify(detail='设备名称不正确。'), 400
                device_id, name = device_id.strip(), name.strip()
                self.devices = {token: device for token, device in self.devices.items()
                                if device['device_id'] != device_id}
                token = secrets.token_urlsafe(32)
                self.devices[token] = {'device_id': device_id, 'name': name}
                self.failed_attempts.pop(address, None)
            return jsonify(token=token, device_id=device_id, name=NAME, protocol=2,
                           sync_available=self.library is not None, **self.speech.capabilities())

        @self.app.get('/api/sync/v2/status')
        def sync_status():
            return jsonify(protocol=2, name=NAME, paired=True, device_id=g.sync_device['device_id'],
                           sync_available=self.library is not None, **self.speech.capabilities())

        @self.app.post('/api/sync/v2/tts/start')
        def sync_tts_start():
            request.max_content_length = 4096
            payload = request.get_json(silent=True)
            with self.transfer_lock:
                require_current_pairing()
                entity = self.speech.entity(payload)
            return jsonify(self.speech.start(payload, entity, g.sync_speech_owner, require_current_pairing))

        @self.app.route('/api/sync/v2/tts/tasks/<tid>', methods=['GET', 'DELETE'])
        def sync_tts_task(tid):
            require_current_pairing()
            return jsonify(self.speech.task(tid, g.sync_speech_owner, cancel=request.method == 'DELETE'))

        @self.app.get('/api/sync/v2/manifest')
        def sync_manifest():
            if self.library is None:
                return jsonify(detail='文库传输未就绪。'), 503
            with self.transfer_lock:
                require_current_pairing()
                return jsonify(self.library.manifest())

        @self.app.post('/api/sync/v2/pull')
        def sync_pull():
            request.max_content_length = 4 * 1024 * 1024
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify(detail='同步清单格式不正确。'), 400
            key, known = payload.get('key'), payload.get('known_files', {})
            if (not isinstance(key, str) or not key or len(key) > 500
                    or not isinstance(known, dict) or len(known) > 10000
                    or any(not isinstance(path, str) or type(size) is not int or size < 0
                           for path, size in known.items())):
                return jsonify(detail='同步路径或文件大小格式不正确。'), 400
            if self.library is None:
                return jsonify(detail='文库传输未就绪。'), 503
            with self.transfer_lock:
                require_current_pairing()
                blob = self.library.export_bundle(key, known_files=known)
                return send_file(io.BytesIO(blob), mimetype='application/zip', download_name='fujimi-library.zip')

        @self.app.route('/api/sync/v2/bundle', methods=['GET', 'POST'])
        def sync_bundle():
            if self.library is None:
                return jsonify(detail='文库传输未就绪。'), 503
            with self.transfer_lock:
                require_current_pairing()
                if request.method == 'POST':
                    if request.mimetype != 'application/zip':
                        return jsonify(detail='请发送 ZIP 格式的文库文件。'), 415
                    blob = request.get_data()
                    require_current_pairing()
                    return jsonify(self.library.import_bundle(blob))
                key = request.args.get('key', '')
                if not key or len(key) > 500:
                    return jsonify(detail='请选择需要同步的文库条目。'), 400
                blob = self.library.export_bundle(key)
                response = send_file(io.BytesIO(blob), mimetype='application/zip', download_name='fujimi-library.zip')
                return response
