"""Pairing boundaries exercised without binding an active library or LAN port."""
import importlib.util
import hashlib
import io
import json
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from flask import Flask
from PIL import Image


class SyncAddressTests(unittest.TestCase):
    @staticmethod
    def adapter(address, *, hardware=True, up=True, gateway=None, metric=35):
        return {'hardware': hardware, 'up': up, 'addresses': [address],
                'gateways': [gateway] if gateway else [], 'metric': metric}

    def select_windows(self, adapters):
        from device_sync import recommended_private_address
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps(adapters), stderr='')
        with patch('device_sync.os.name', 'nt'), patch('subprocess.run', return_value=result) as run, \
                patch('device_sync.socket.socket') as route, \
                patch('device_sync.socket.getaddrinfo', return_value=[]):
            route.return_value.__enter__.return_value.getsockname.return_value = ('172.28.200.219', 0)
            address = recommended_private_address()
        return address, run, route

    def test_windows_prefers_physical_wlan_over_vpn_route(self):
        address, run, route = self.select_windows([
            self.adapter('172.28.200.219', hardware=False, metric=1),
            self.adapter('198.18.0.1', hardware=False, metric=1),
            self.adapter('192.168.1.3', gateway='192.168.1.1'),
        ])
        self.assertEqual(address, '192.168.1.3')
        run.assert_called_once()
        self.assertTrue(run.call_args.kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)
        self.assertLessEqual(run.call_args.kwargs['timeout'], 10)
        route.assert_not_called()

    def test_windows_prefers_gateway_then_metric_without_adapter_name_rules(self):
        address, _, _ = self.select_windows([
            self.adapter('10.20.0.2', metric=1),
            self.adapter('172.28.200.219', hardware=False, gateway='172.28.200.1', metric=1),
            self.adapter('192.168.5.2', gateway='192.168.5.1', metric=80),
            self.adapter('192.168.1.3', gateway='192.168.1.1', metric=35),
            self.adapter('192.168.9.2', up=False, gateway='192.168.9.1', metric=1),
        ])
        self.assertEqual(address, '192.168.1.3')

    def test_windows_can_use_direct_physical_lan_without_gateway(self):
        address, _, _ = self.select_windows([
            self.adapter('172.28.200.219', hardware=False),
            self.adapter('10.20.0.2'),
        ])
        self.assertEqual(address, '10.20.0.2')

    def test_windows_does_not_advertise_virtual_or_nonprivate_interfaces(self):
        address, _, _ = self.select_windows([
            self.adapter('172.28.200.219', hardware=False),
            self.adapter('169.254.100.2'),
            self.adapter('203.0.113.2', gateway='203.0.113.1'),
        ])
        self.assertIsNone(address)

    def test_windows_adapter_query_failure_does_not_reuse_vpn_route(self):
        from device_sync import recommended_private_address
        for failure in (OSError('PowerShell unavailable'), subprocess.TimeoutExpired('powershell', 10)):
            with self.subTest(failure=type(failure).__name__), patch('device_sync.os.name', 'nt'), \
                    patch('subprocess.run', side_effect=failure), patch('device_sync.socket.socket') as route, \
                    patch('device_sync.socket.getaddrinfo', return_value=[]):
                route.return_value.__enter__.return_value.getsockname.return_value = ('172.28.200.219', 0)
                self.assertIsNone(recommended_private_address())
                route.assert_not_called()


class DormantServer:
    def __init__(self, host, port, app):
        self.host = host
        self.port = port
        self.stopped = threading.Event()

    def serve_forever(self):
        self.stopped.wait(3)

    def shutdown(self):
        self.stopped.set()

    def server_close(self):
        self.stopped.set()


class DeviceSyncTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('device_sync'),
                             'The independent device sync service is not implemented.')
        from device_sync import DeviceSync
        self.runtime = DeviceSync()
        self.addCleanup(self.runtime.shutdown)
        self.app = Flask('sync-control-test')
        self.runtime.register_control(self.app)
        self.control = self.app.test_client()
        self.lan = self.runtime.app.test_client()
        self.host_patch = patch('device_sync.recommended_private_address', return_value='192.168.1.12')
        self.server_patch = patch('device_sync.make_sync_server', side_effect=DormantServer)
        self.host_patch.start()
        self.server_patch.start()
        self.addCleanup(self.host_patch.stop)
        self.addCleanup(self.server_patch.stop)

    def enable(self):
        response = self.control.put('/api/settings/device-sync', json={'enabled': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def lan_request(self, path, method='GET', **kwargs):
        return self.lan.open(path, method=method, base_url='http://192.168.1.12:8429',
                             environ_base={'REMOTE_ADDR': '192.168.1.20'}, **kwargs)

    def pair(self):
        state = self.enable()
        result = self.lan_request('/api/sync/v2/pair', 'POST',
            json={'code': state['pairing_code'], 'device_id': 'phone-1', 'device_name': 'Android'})
        self.assertEqual(result.status_code, 200, result.get_json())
        return result.get_json()

    def test_disabled_by_default_and_control_does_not_open_lan(self):
        response = self.control.get('/api/settings/device-sync')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['enabled'])
        self.assertEqual(response.json['pairing_code'], '')
        self.assertEqual(self.lan_request('/api/sync/v2/info').status_code, 503)

    def test_pairing_requires_code_and_returns_a_working_token(self):
        state = self.enable()
        self.assertEqual(state['url'], 'http://192.168.1.12:8429')
        self.assertRegex(state['pairing_code'], r'^\d{6}$')
        bad = self.lan_request('/api/sync/v2/pair', 'POST',
            json={'code': 'bad', 'device_id': 'phone-1', 'device_name': 'Android'})
        self.assertEqual(bad.status_code, 401)
        info = self.lan_request('/api/sync/v2/info').get_json()
        self.assertTrue(info['pairing_required'])
        self.assertNotIn('pairing_code', info)
        paired = self.pair()
        self.assertEqual(paired['protocol'], 2)
        self.assertGreaterEqual(len(paired['token']), 32)
        status = self.lan_request('/api/sync/v2/status',
                                  headers={'Authorization': 'Bearer ' + paired['token']})
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json['device_id'], 'phone-1')
        self.assertEqual(self.lan_request('/api/sync/v2/status').status_code, 401)
        control = self.control.get('/api/settings/device-sync').get_json()
        self.assertEqual(control['paired_devices'][0]['name'], 'Android')
        self.assertNotIn('token', json.dumps(control))

    def test_disable_revokes_tokens_and_reenable_rotates_credentials(self):
        paired = self.pair()
        headers = {'Authorization': 'Bearer ' + paired['token']}
        self.control.put('/api/settings/device-sync', json={'enabled': False})
        self.assertEqual(self.lan_request('/api/sync/v2/status', headers=headers).status_code, 503)
        self.enable()
        self.assertEqual(self.lan_request('/api/sync/v2/status', headers=headers).status_code, 401)
        self.assertEqual(self.control.get('/api/settings/device-sync').json['paired_devices'], [])

    def test_control_rejects_remote_and_browser_cross_origin_requests(self):
        cases = [
            {'environ_base': {'REMOTE_ADDR': '192.168.1.20'}},
            {'headers': {'Origin': 'https://unrelated.example'}},
            {'headers': {'Origin': 'null'}},
            {'headers': {'Sec-Fetch-Site': 'cross-site'}},
            {'base_url': 'http://unrelated.example'},
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertEqual(self.control.put('/api/settings/device-sync',
                    json={'enabled': True}, **extra).status_code, 403)
        response = self.control.put('/api/settings/device-sync', json={'enabled': True},
                                    headers={'Origin': 'http://localhost'})
        self.assertEqual(response.status_code, 200)

    def test_control_requires_boolean_enabled(self):
        for value in ('true', 1, None):
            with self.subTest(value=value):
                response = self.control.put('/api/settings/device-sync', json={'enabled': value})
                self.assertEqual(response.status_code, 400)

    def test_no_private_interface_reports_error_without_enabling(self):
        with patch('device_sync.recommended_private_address', return_value=None):
            response = self.control.put('/api/settings/device-sync', json={'enabled': True})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json['enabled'])
        self.assertTrue(response.json['detail'])

    def test_wrong_pairing_code_is_rate_limited(self):
        self.enable()
        for _ in range(5):
            result = self.lan_request('/api/sync/v2/pair', 'POST',
                                      json={'code': 'bad', 'device_id': 'phone-1'})
            self.assertEqual(result.status_code, 401)
        result = self.lan_request('/api/sync/v2/pair', 'POST',
                                  json={'code': 'bad', 'device_id': 'phone-1'})
        self.assertEqual(result.status_code, 429)
        self.assertIn('Retry-After', result.headers)

    def test_non_ascii_pairing_code_is_rejected_without_server_error(self):
        self.enable()
        result = self.lan_request('/api/sync/v2/pair', 'POST',
                                  json={'code': '１２３４５６', 'device_id': 'phone-1'})
        self.assertEqual(result.status_code, 401)

    def test_queued_transfer_rechecks_pairing_after_shutdown(self):
        self.runtime.library = object()
        result = []
        entered = threading.Event()
        @self.runtime.app.before_request
        def waiting_for_transfer():
            entered.set()
        paired = self.pair()
        entered.clear()
        self.runtime.transfer_lock.acquire()
        thread = threading.Thread(target=lambda: result.append(self.lan_request('/api/sync/v2/manifest',
            headers={'Authorization': 'Bearer ' + paired['token']})))
        thread.start()
        self.assertTrue(entered.wait(2))
        self.runtime.shutdown()
        self.runtime.transfer_lock.release()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0].status_code, 401)

    def test_qr_is_local_png_and_contains_current_pairing_payload(self):
        state = self.enable()
        import qrcode
        with patch('qrcode.make', wraps=qrcode.make) as make:
            response = self.control.get(state['qr_url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/png')
        image = Image.open(io.BytesIO(response.data))
        self.assertGreater(image.width, 100)
        encoded = json.loads(make.call_args.args[0])
        self.assertEqual(encoded, {'type': 'fujimi-sync', 'version': 2,
                                  'url': state['url'], 'code': state['pairing_code']})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_lan_has_no_local_management_routes_and_rejects_browser_origin(self):
        self.enable()
        self.assertEqual(self.lan_request('/api/settings/voice-mode').status_code, 404)
        self.assertEqual(self.lan_request('/api/sync/v2/info',
                         headers={'Origin': 'https://unrelated.example'}).status_code, 403)

    def test_incremental_pull_passes_path_sizes_without_content_hashing(self):
        from unittest.mock import Mock
        library = Mock()
        library.export_bundle.return_value = b'zip-fixture'
        library.import_bundle.return_value = {'status': 'created'}
        self.runtime.library = library
        auth = {'Authorization': 'Bearer ' + self.pair()['token']}
        known = {'audio/七海.mp3': 12000000, 'original.txt': 24}
        response = self.lan_request('/api/sync/v2/pull', 'POST', headers=auth,
                                    json={'key': 'article:fixture', 'known_files': known})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.data, b'zip-fixture')
        self.assertNotIn('X-Content-SHA256', response.headers)
        library.export_bundle.assert_called_once_with('article:fixture', known_files=known)
        uploaded = self.lan_request('/api/sync/v2/bundle', 'POST', data=b'zip-fixture',
                                   content_type='application/zip', headers={**auth, 'X-Content-SHA256': 'ignored-old-header'})
        self.assertEqual(uploaded.status_code, 200)
        library.import_bundle.assert_called_once_with(b'zip-fixture')
        for known_files in [[], {'audio/a.mp3': -1}, {'a': True}, {'a': '123'}]:
            response = self.lan_request('/api/sync/v2/pull', 'POST', headers=auth,
                                        json={'key': 'article:fixture', 'known_files': known_files})
            self.assertEqual(response.status_code, 400)

    def test_authenticated_bundle_transfers_real_example_without_hash_header(self):
        from article_store import ArticleStore
        from book_store import BookStore
        from example_store import ExampleStore
        from library_sync import LibrarySync
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            article_source, article_target = ArticleStore(source), ArticleStore(target)
            examples_source = ExampleStore(source, article_source)
            examples_target = ExampleStore(target, article_target)
            examples_source.create('端末同期', '共有する文章。', translated_paragraphs=['共享正文。'])
            self.runtime.library = LibrarySync(article_source, BookStore(source), examples_source)
            paired = self.pair()
            auth = {'Authorization': 'Bearer ' + paired['token']}
            self.assertTrue(paired['sync_available'])
            self.assertEqual(self.lan_request('/api/sync/v2/manifest').status_code, 401)
            manifest = self.lan_request('/api/sync/v2/manifest', headers=auth)
            self.assertEqual(manifest.status_code, 200, manifest.get_json())
            item = next(item for item in manifest.json['items'] if item['title'] == '端末同期')
            bundle = self.lan_request('/api/sync/v2/bundle', headers=auth, query_string={'key': item['key']})
            self.assertEqual(bundle.status_code, 200, bundle.get_json())
            self.assertEqual(bundle.mimetype, 'application/zip')
            self.assertNotIn('X-Content-SHA256', bundle.headers)
            self.runtime.library = LibrarySync(article_target, BookStore(target), examples_target)
            invalid = self.lan_request('/api/sync/v2/bundle', 'POST', data=b'not a zip',
                content_type='application/zip', headers=auth)
            self.assertEqual(invalid.status_code, 400)
            self.assertFalse(any(item['title'] == '端末同期' for item in examples_target.list()))
            imported = self.lan_request('/api/sync/v2/bundle', 'POST', data=bundle.data,
                content_type='application/zip', headers=auth)
            self.assertEqual(imported.status_code, 200, imported.get_json())
            self.assertEqual(imported.json['status'], 'created')
            saved = next(item for item in examples_target.list() if item['title'] == '端末同期')
            self.assertEqual(saved['text'], '共有する文章。')
            self.assertEqual(saved['translated_paragraphs'], ['共享正文。'])


class ServerDeviceSyncTests(unittest.TestCase):
    def test_main_app_exposes_disabled_sync_using_its_library_stores(self):
        from server import create_app
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder)
            try:
                response = app.test_client().get('/api/settings/device-sync')
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json['enabled'])
                self.assertIsNotNone(app.extensions['device_sync'].library)
                self.assertIsNone(app.extensions['device_sync'].server)
                voices = app.extensions['device_sync'].library.manifest()['browser_voices']
                self.assertIn('kokoro:jf_alpha', [voice['id'] for voice in voices])
                self.assertTrue(all(set(voice) == {'id', 'name', 'provider', 'lang'} for voice in voices))
            finally:
                app.extensions['tts'].close()
                app.extensions['browser_tts'].close()
                if 'device_sync' in app.extensions:
                    app.extensions['device_sync'].shutdown()


if __name__ == '__main__':
    unittest.main()
