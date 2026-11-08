"""Opt-in local Tailscale CLI connection, with no VPN ownership or settings changes."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlsplit


TAILSCALE_NETWORK = ipaddress.ip_network('100.64.0.0/10')


def tailscale_ipv4(value):
    if not isinstance(value, str):
        return False
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and address in TAILSCALE_NETWORK
    except (ValueError, TypeError):
        return False


def safe_login_url(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return ''
    try:
        url = urlsplit(value)
        return value if (url.scheme == 'https' and url.hostname == 'login.tailscale.com'
                         and url.port in (None, 443) and not url.username and not url.password
                         and url.path.startswith('/a/') and not url.fragment) else ''
    except ValueError:
        return ''


def find_tailscale():
    executable = shutil.which('tailscale')
    if executable:
        return executable
    for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        directory = os.environ.get(key)
        if directory:
            candidate = Path(directory) / 'Tailscale' / 'tailscale.exe'
            if candidate.is_file():
                return str(candidate)
    return None


def start_tailscale_gui(executable):
    """Start only the installed sibling UI; never install or control the VPN service."""
    gui = Path(executable).with_name('tailscale-ipn.exe')
    if not gui.is_file():
        return False
    try:
        subprocess.Popen([str(gui)], shell=False, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                         close_fds=True)
        return True
    except OSError:
        return False


@dataclass(frozen=True)
class TailscaleConnection:
    host: str = ''
    status: str = 'unavailable'


class TailscaleError(ValueError):
    def __init__(self, detail, *, status='error', login_url=''):
        super().__init__(detail)
        self.status = status
        self.login_url = safe_login_url(login_url)


class _DaemonUnavailable(TailscaleError):
    pass


class TailscaleConnector:
    """Only called on explicit enable. Closing library sync never calls this CLI."""
    def __init__(self, *, timeout=18):
        self.timeout = max(0.01, min(float(timeout), 18))

    @staticmethod
    def _run(executable, arguments, timeout):
        return subprocess.run([executable, *arguments], shell=False, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                              check=False, timeout=timeout,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def connect(self, *, cancelled=lambda: False):
        executable = find_tailscale()
        if not executable:
            return TailscaleConnection()
        deadline = time.monotonic() + self.timeout

        def check_cancelled():
            if cancelled():
                raise TailscaleError('连接已取消。')

        def snapshot():
            check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TailscaleError('Tailscale 客户端初始化或连接超时，请在客户端检查状态后重试。')
            try:
                result = self._run(executable, ['status', '--json'], min(3, remaining))
                if result.returncode:
                    raise _DaemonUnavailable('无法连接 Tailscale 服务，请打开 Tailscale 并确认服务正在运行。')
                value = json.loads(result.stdout)
                if not isinstance(value, dict) or not isinstance(value.get('BackendState'), str):
                    raise ValueError('Invalid status')
            except subprocess.TimeoutExpired:
                raise TailscaleError('读取 Tailscale 状态超时，请检查 Tailscale 服务后重试。') from None
            except (OSError, ValueError) as error:
                if isinstance(error, TailscaleError):
                    raise
                raise TailscaleError('无法读取 Tailscale 状态，请打开 Tailscale 并确认服务正在运行。') from None
            check_cancelled()
            return value

        def ready(value):
            own = value.get('Self')
            if value['BackendState'] != 'Running' or not isinstance(own, dict) or own.get('Online') is not True:
                return None
            addresses = own.get('TailscaleIPs')
            if not isinstance(addresses, list):
                return None
            return next((address for address in addresses if tailscale_ipv4(address)), None)

        def login_required(value):
            raise TailscaleError('请先在 Tailscale 中完成登录，再重新开启文庫互联。',
                                 status='login_required', login_url=value.get('AuthURL'))

        gui_started = False

        def open_client():
            nonlocal gui_started
            check_cancelled()
            if not gui_started:
                if not start_tailscale_gui(executable):
                    raise TailscaleError('无法自动打开 Tailscale 客户端，请检查客户端是否安装完整。')
                gui_started = True

        try:
            value = snapshot()
        except _DaemonUnavailable:
            open_client()
            while True:
                try:
                    value = snapshot()
                    break
                except _DaemonUnavailable:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TailscaleError('Tailscale 服务仍未就绪，请在 Tailscale 中检查服务和登录状态。') from None
                    time.sleep(min(0.25, remaining))
        up_attempted = False
        while True:
            check_cancelled()
            address = ready(value)
            if address:
                return TailscaleConnection(address, 'ready')
            state = value['BackendState']
            if state == 'NeedsMachineAuth':
                raise TailscaleError('此设备等待 Tailscale 管理员批准，请批准后重试。')
            if state in ('NoState', 'Starting', 'Stopped', 'NeedsLogin'):
                open_client()
            if state == 'NeedsLogin' and (safe_login_url(value.get('AuthURL')) or up_attempted):
                login_required(value)
            if state in ('Stopped', 'NeedsLogin') and not up_attempted:
                check_cancelled()
                up_attempted = True
                try:
                    # Restore saved preferences only after the client has initialized.
                    remaining = max(0.01, deadline - time.monotonic())
                    result = self._run(executable, ['up'], min(12, remaining))
                    up_failed = bool(result.returncode)
                except subprocess.TimeoutExpired:
                    up_failed = False
                except OSError:
                    raise TailscaleError('无法启动 Tailscale 连接，请在 Tailscale 客户端检查状态后重试。') from None
                value = snapshot()
                if up_failed and value['BackendState'] != 'NeedsLogin' and not ready(value):
                    raise TailscaleError('Tailscale 未能连接，请在 Tailscale 中检查登录及网络状态后重试。')
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TailscaleError('Tailscale 尚未在线或没有可用的本机 IPv4 地址，请连接成功后重试。')
            time.sleep(min(0.25, remaining))
            value = snapshot()
