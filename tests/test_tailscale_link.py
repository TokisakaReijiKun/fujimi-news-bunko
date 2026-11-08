"""Offline Tailscale integration checks; never contact a real daemon or VPN."""
import importlib
import importlib.util
import inspect
import json
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from flask import Flask


CLI = r'C:\Program Files\Tailscale\tailscale.exe'
ADDRESS = '100.101.102.103'


def status(state='Running', *, online=True, addresses=None, auth=''):
    return {'BackendState': state, 'Self': {'Online': online,
            'TailscaleIPs': [ADDRESS] if addresses is None else addresses}, 'AuthURL': auth}


def completed(payload=None, *, code=0, text=''):
    return subprocess.CompletedProcess([], code, stdout=json.dumps(payload) if payload is not None else text,
                                       stderr='sensitive daemon diagnostic')


class TailscaleConnectorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('tailscale_link'),
                             'The opt-in Tailscale connector is missing.')
        self.module = importlib.import_module('tailscale_link')
        self.find = patch('tailscale_link.find_tailscale', return_value=CLI)
        self.find.start()
        self.addCleanup(self.find.stop)
        self.gui = patch('tailscale_link.start_tailscale_gui', return_value=True, create=True)
        self.gui_mock = self.gui.start()
        self.addCleanup(self.gui.stop)

    def connect(self, outputs):
        with patch('tailscale_link.subprocess.run', side_effect=outputs) as run:
            result = self.module.TailscaleConnector().connect()
        return result, run

    def test_running_online_reuses_address_without_up(self):
        result, run = self.connect([completed(status())])
        self.assertEqual((result.host, result.status), (ADDRESS, 'ready'))
        self.assertEqual(run.call_args.args[0], [CLI, 'status', '--json'])
        self.assertEqual(run.call_count, 1)
        self.gui_mock.assert_not_called()

    def test_stopped_restores_without_changing_existing_preferences(self):
        result, run = self.connect([completed(status('Stopped', online=False)), completed(), completed(status())])
        self.assertEqual(result.host, ADDRESS)
        self.assertEqual(run.call_args_list[1].args[0], [CLI, 'up'])
        for call in run.call_args_list:
            self.assertIsInstance(call.args[0], list)
            self.assertFalse(call.kwargs['shell'])
            self.assertLessEqual(call.kwargs['timeout'], 18)
            self.assertTrue(call.kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)

    def test_missing_cli_allows_lan_without_subprocess(self):
        with patch('tailscale_link.find_tailscale', return_value=None), \
                patch('tailscale_link.subprocess.run') as run:
            result = self.module.TailscaleConnector().connect()
        self.assertEqual((result.host, result.status), ('', 'unavailable'))
        run.assert_not_called()

    def test_needs_login_returns_only_official_action_url(self):
        url = 'https://login.tailscale.com/a/abc123'
        with patch('tailscale_link.subprocess.run', return_value=completed(status('NeedsLogin', online=False, auth=url))) as run:
            with self.assertRaises(self.module.TailscaleError) as raised:
                self.module.TailscaleConnector().connect()
        self.assertEqual(raised.exception.status, 'login_required')
        self.assertEqual(raised.exception.login_url, url)
        self.assertNotIn('sensitive', str(raised.exception))
        self.assertEqual(run.call_count, 1)
        self.gui_mock.assert_called_once_with(CLI)

    def test_nostate_opens_gui_even_when_daemon_is_already_reachable(self):
        result, run = self.connect([completed(status('NoState', online=False, addresses=[])),
                                    completed(status())])
        self.assertEqual(result.host, ADDRESS)
        self.gui_mock.assert_called_once_with(CLI)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [[CLI, 'status', '--json'], [CLI, 'status', '--json']])

    def test_nostate_waits_for_initialization_without_reporting_login_required(self):
        with patch('tailscale_link.subprocess.run',
                   return_value=completed(status('NoState', online=False, addresses=[]))):
            with self.assertRaises(self.module.TailscaleError) as raised:
                self.module.TailscaleConnector(timeout=0.01).connect()
        self.gui_mock.assert_called_once_with(CLI)
        self.assertEqual(raised.exception.status, 'error')
        self.assertNotIn('请先在 Tailscale 中完成登录', str(raised.exception))

    def test_nostate_without_launchable_gui_is_actionable(self):
        self.gui_mock.return_value = False
        with patch('tailscale_link.subprocess.run',
                   return_value=completed(status('NoState', online=False, addresses=[]))) as run:
            with self.assertRaises(self.module.TailscaleError) as raised:
                self.module.TailscaleConnector().connect()
        self.gui_mock.assert_called_once_with(CLI)
        self.assertEqual(raised.exception.status, 'error')
        self.assertIn('客户端', str(raised.exception))
        self.assertEqual(run.call_count, 1)

    def test_nostate_up_can_generate_login_but_never_claim_connected(self):
        url = 'https://login.tailscale.com/a/fresh'
        outputs = [completed(status('NoState', online=False, addresses=[])),
                   completed(status('NeedsLogin', online=False, addresses=[])),
                   subprocess.TimeoutExpired([CLI, 'up'], 12),
                   completed(status('NeedsLogin', online=False, addresses=[], auth=url))]
        with patch('tailscale_link.subprocess.run', side_effect=outputs) as run:
            with self.assertRaises(self.module.TailscaleError) as raised:
                self.module.TailscaleConnector().connect()
        self.assertEqual(raised.exception.status, 'login_required')
        self.assertEqual(raised.exception.login_url, url)
        self.assertEqual(run.call_args_list[2].args[0], [CLI, 'up'])
        self.gui_mock.assert_called_once_with(CLI)

    def test_running_requires_self_online_and_cgnat_ipv4(self):
        invalid = [status(online=False), status(addresses=['192.168.1.3']),
                   status(addresses=['100.63.255.255']), status(addresses=['100.128.0.1']),
                   status(addresses=['fd7a:115c:a1e0::1']), status(addresses=['8.8.8.8'])]
        for payload in invalid:
            with self.subTest(payload=payload), patch('tailscale_link.subprocess.run', return_value=completed(payload)):
                with self.assertRaises(self.module.TailscaleError):
                    self.module.TailscaleConnector(timeout=0.01).connect()

    def test_missing_daemon_and_invalid_json_do_not_expose_output(self):
        for result in [completed(code=1, text='private-account@example.com'), completed(text='not json')]:
            with self.subTest(result=result.returncode), patch('tailscale_link.subprocess.run', return_value=result):
                with self.assertRaises(self.module.TailscaleError) as raised:
                    self.module.TailscaleConnector().connect()
            self.assertEqual(raised.exception.status, 'error')
            self.assertNotIn('private-account', str(raised.exception))
            self.assertNotIn('sensitive', str(raised.exception))

    def test_timeout_and_execution_failure_are_actionable_without_raw_error(self):
        for failure in [subprocess.TimeoutExpired(CLI, 3, output='secret'), OSError('secret path')]:
            with self.subTest(failure=type(failure).__name__), patch('tailscale_link.subprocess.run', side_effect=failure):
                with self.assertRaises(self.module.TailscaleError) as raised:
                    self.module.TailscaleConnector().connect()
                self.assertEqual(raised.exception.status, 'error')
                self.assertNotIn('secret', str(raised.exception))

    def test_up_failure_never_resets_or_reuses_lan(self):
        with patch('tailscale_link.subprocess.run', side_effect=[completed(status('Stopped', online=False)),
                completed(code=1), completed(status('Stopped', online=False))]) as run:
            with self.assertRaises(self.module.TailscaleError):
                self.module.TailscaleConnector().connect()
        self.assertEqual(run.call_args_list[1].args[0], [CLI, 'up'])

    def test_daemon_unavailable_launches_installed_gui_once_then_verifies_status(self):
        self.gui_mock.return_value = True
        result, run = self.connect([completed(code=1), completed(status())])
        self.assertEqual(result.host, ADDRESS)
        self.gui_mock.assert_called_once_with(CLI)
        self.assertEqual(run.call_count, 2)

    def test_daemon_unavailable_without_gui_is_actionable_and_does_not_run_up(self):
        self.gui_mock.return_value = False
        with patch('tailscale_link.subprocess.run', return_value=completed(code=1)) as run:
            with self.assertRaises(self.module.TailscaleError) as raised:
                self.module.TailscaleConnector().connect()
        self.gui_mock.assert_called_once_with(CLI)
        self.assertIn('Tailscale', str(raised.exception))
        self.assertEqual(run.call_count, 1)

    def test_gui_start_does_not_claim_connected_when_daemon_never_becomes_ready(self):
        self.gui_mock.return_value = True
        with patch('tailscale_link.subprocess.run', return_value=completed(code=1)):
            with self.assertRaises(self.module.TailscaleError):
                self.module.TailscaleConnector(timeout=0.01).connect()
        self.gui_mock.assert_called_once_with(CLI)

    def test_login_urls_reject_untrusted_hosts_credentials_and_non_https(self):
        invalid = ['http://login.tailscale.com/a/abc', 'https://login.tailscale.com.evil.test/a/abc',
                   'https://login.tailscale.com@evil.test/a/abc', 'https://evil.test/a/abc',
                   'https://user:password@login.tailscale.com/a/abc',
                   'https://login.tailscale.com:444/a/abc', 'javascript:alert(1)']
        for url in invalid:
            self.assertEqual(self.module.safe_login_url(url), '', url)


class TailscaleDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('tailscale_link'), 'Tailscale discovery is missing.')
        self.module = importlib.import_module('tailscale_link')

    def test_path_with_spaces_is_returned_unquoted_for_argument_array(self):
        with patch('tailscale_link.shutil.which', return_value=CLI):
            self.assertEqual(self.module.find_tailscale(), CLI)

    def test_standard_windows_directory_fallback_without_hardcoded_user_path(self):
        with tempfile.TemporaryDirectory() as folder:
            from pathlib import Path
            executable = Path(folder) / 'Tailscale' / 'tailscale.exe'
            executable.parent.mkdir()
            executable.write_bytes(b'fixture only')
            with patch('tailscale_link.shutil.which', return_value=None), \
                    patch.dict('tailscale_link.os.environ', {'ProgramFiles': folder}, clear=True):
                self.assertEqual(self.module.find_tailscale(), str(executable))

    def test_gui_launch_opens_only_existing_sibling_without_a_console(self):
        self.assertTrue(hasattr(self.module, 'start_tailscale_gui'), 'Installed GUI launch is missing.')
        with tempfile.TemporaryDirectory() as folder:
            from pathlib import Path
            executable = Path(folder) / 'Tailscale Space' / 'tailscale.exe'
            executable.parent.mkdir()
            gui = executable.with_name('tailscale-ipn.exe')
            gui.write_bytes(b'fixture only')
            with patch('tailscale_link.subprocess.Popen') as launch:
                self.assertTrue(self.module.start_tailscale_gui(str(executable)))
            self.assertEqual(launch.call_args.args[0], [str(gui)])
            self.assertFalse(launch.call_args.kwargs['shell'])
            self.assertTrue(launch.call_args.kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)
            self.assertIsNone(launch.call_args.kwargs.get('startupinfo'))
            gui.unlink()
            with patch('tailscale_link.subprocess.Popen') as launch:
                self.assertFalse(self.module.start_tailscale_gui(str(executable)))
            launch.assert_not_called()


class SyncTailscaleBoundaryTests(unittest.TestCase):
    def setUp(self):
        from device_sync import DeviceSync
        self.assertIn('connector', inspect.signature(DeviceSync).parameters,
                      'DeviceSync cannot inject a Tailscale connector yet.')
        self.module = importlib.import_module('tailscale_link')
        self.connector = Mock()
        self.connector.connect.return_value = self.module.TailscaleConnection(ADDRESS, 'ready')
        self.runtime = DeviceSync(connector=self.connector)
        self.addCleanup(self.runtime.shutdown)
        self.app = Flask('tailscale-control-test')
        self.runtime.register_control(self.app)
        self.control = self.app.test_client()
        from test_device_sync import DormantServer
        self.bind = patch('device_sync.make_sync_server', side_effect=DormantServer)
        self.bind_mock = self.bind.start()
        self.addCleanup(self.bind.stop)
        self.lan = patch('device_sync.recommended_private_address', return_value='192.168.1.12')
        self.lan_mock = self.lan.start()
        self.addCleanup(self.lan.stop)

    def enable(self):
        return self.control.put('/api/settings/device-sync', json={'enabled': True})

    def info(self, remote, *, host=ADDRESS, headers=None):
        return self.runtime.app.test_client().get('/api/sync/v2/info',
                base_url=f'http://{host}:8429', environ_base={'REMOTE_ADDR': remote}, headers=headers or {})

    def test_only_verified_tailscale_ip_is_bound_and_advertised(self):
        response = self.enable()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['url'], f'http://{ADDRESS}:8429')
        self.assertEqual(response.json['network'], 'tailscale')
        self.assertEqual(response.json['tailscale_status'], 'ready')
        self.assertEqual(self.bind_mock.call_args.args[0], ADDRESS)
        self.lan_mock.assert_not_called()

    def test_tailscale_source_allowed_only_on_tailscale_listener(self):
        self.assertEqual(self.enable().status_code, 200)
        self.assertEqual(self.info('100.64.0.1').status_code, 200)
        self.assertEqual(self.info('100.127.255.254').status_code, 200)
        for remote in ['8.8.8.8', '100.63.255.255', '100.128.0.1', '198.18.0.1']:
            self.assertEqual(self.info(remote).status_code, 403)
        self.assertEqual(self.info('100.64.0.1', host='192.168.1.12').status_code, 403)
        self.assertEqual(self.info('100.64.0.1', headers={'Origin': 'https://other.test'}).status_code, 403)
        self.runtime.shutdown()
        self.connector.connect.return_value = self.module.TailscaleConnection()
        self.assertEqual(self.enable().status_code, 200)
        self.assertEqual(self.info('100.64.0.1', host='192.168.1.12').status_code, 403)
        self.assertEqual(self.info('192.168.1.20', host='192.168.1.12').status_code, 200)

    def test_tailscale_pairing_keeps_token_required_and_qr_host(self):
        enabled = self.enable().json
        client = self.runtime.app.test_client()
        kwargs = {'base_url': f'http://{ADDRESS}:8429', 'environ_base': {'REMOTE_ADDR': '100.64.0.2'}}
        self.assertEqual(client.get('/api/sync/v2/status', **kwargs).status_code, 401)
        pair = client.post('/api/sync/v2/pair', json={'device_id': 'phone', 'code': enabled['pairing_code']}, **kwargs)
        self.assertEqual(pair.status_code, 200)
        self.assertEqual(client.get('/api/sync/v2/status', headers={'Authorization': 'Bearer ' + pair.json['token']},
                                   **kwargs).status_code, 200)
        import qrcode
        with patch('qrcode.make', wraps=qrcode.make) as make:
            self.assertEqual(self.control.get(enabled['qr_url']).status_code, 200)
        self.assertEqual(json.loads(make.call_args.args[0])['url'], f'http://{ADDRESS}:8429')

    def test_installed_login_failure_exposes_safe_action_not_lan(self):
        self.connector.connect.side_effect = self.module.TailscaleError('请先登录 Tailscale。',
                status='login_required', login_url='https://login.tailscale.com/a/test')
        response = self.enable()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json['enabled'])
        self.assertEqual(response.json['tailscale_status'], 'login_required')
        self.assertEqual(response.json['login_url'], 'https://login.tailscale.com/a/test')
        self.assertEqual(response.json['url'], '')
        self.bind_mock.assert_not_called()
        self.lan_mock.assert_not_called()

    def test_invalid_connector_ip_cannot_open_public_listener(self):
        self.connector.connect.return_value = self.module.TailscaleConnection('0.0.0.0', 'ready')
        self.assertEqual(self.enable().status_code, 503)
        self.bind_mock.assert_not_called()

    def test_disable_does_not_disconnect_tailscale(self):
        self.assertEqual(self.enable().status_code, 200)
        self.control.put('/api/settings/device-sync', json={'enabled': False})
        self.assertEqual(self.connector.mock_calls[0][0], 'connect')
        self.assertEqual(len(self.connector.mock_calls), 1)
        self.assertFalse(self.runtime.state()['enabled'])

    def test_disable_clears_previous_login_requirement_without_touching_connector(self):
        self.connector.connect.side_effect = self.module.TailscaleError('请先登录 Tailscale。',
                status='login_required', login_url='https://login.tailscale.com/a/test')
        self.assertEqual(self.enable().status_code, 503)
        self.assertEqual(self.runtime.state()['tailscale_status'], 'login_required')
        disabled = self.control.put('/api/settings/device-sync', json={'enabled': False})
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(disabled.json['status'], 'disabled')
        self.assertFalse(disabled.json['enabled'])
        for field in ['network', 'tailscale_status', 'login_url', 'url', 'pairing_code']:
            self.assertEqual(disabled.json[field], '', field)
        self.assertEqual(len(self.connector.mock_calls), 1)
        self.assertEqual(self.connector.mock_calls[0][0], 'connect')
        self.assertEqual(self.control.get('/api/settings/device-sync').json, disabled.json)

    def test_ready_detail_names_tailscale_only_for_tailscale_network(self):
        detail = self.enable().json['detail']
        self.assertIn('Tailscale', detail)
        self.assertIn('手机', detail)
        self.runtime.shutdown()
        self.connector.connect.return_value = self.module.TailscaleConnection()
        lan = self.enable().json
        self.assertNotIn('Tailscale', lan['detail'])
        self.assertIn('扫码', lan['detail'])

    def test_status_and_cancel_remain_available_while_connector_waits(self):
        started, release = threading.Event(), threading.Event()
        def connect(**kwargs):
            started.set()
            release.wait(3)
            return self.module.TailscaleConnection(ADDRESS, 'ready')
        self.connector.connect.side_effect = connect
        results = []
        pending = threading.Thread(target=lambda: results.append(self.enable()))
        pending.start()
        self.assertTrue(started.wait(1))
        try:
            self.assertEqual(self.runtime.state()['status'], 'connecting')
            self.runtime.shutdown()
        finally:
            release.set()
            pending.join(3)
        self.assertFalse(pending.is_alive())
        self.assertFalse(self.runtime.state()['enabled'])
        self.bind_mock.assert_not_called()


class AppConnectorInjectionTests(unittest.TestCase):
    def test_app_factory_is_offline_by_default_and_accepts_explicit_production_connector(self):
        from server import create_app
        self.assertIn('sync_connector', inspect.signature(create_app).parameters,
                      'The app factory has no explicit production connector injection.')
        from tailscale_link import TailscaleConnection
        connector = Mock()
        connector.connect.return_value = TailscaleConnection(ADDRESS, 'ready')
        from test_device_sync import DormantServer
        for injected in [None, connector]:
            with self.subTest(injected=injected is not None), tempfile.TemporaryDirectory() as folder, \
                    patch('tailscale_link.TailscaleConnector.connect') as real_connect, \
                    patch('device_sync.make_sync_server', side_effect=DormantServer), \
                    patch('device_sync.recommended_private_address', return_value='192.168.1.12'):
                app = create_app(folder, sync_connector=injected)
                try:
                    client = app.test_client()
                    self.assertEqual(client.get('/api/settings/device-sync').status_code, 200)
                    response = client.put('/api/settings/device-sync', json={'enabled': True})
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual(response.json['network'], 'tailscale' if injected else 'lan')
                    real_connect.assert_not_called()
                finally:
                    app.extensions['device_sync'].shutdown()
                    app.extensions['tts'].close()
                    app.extensions['browser_tts'].close()
        connector.connect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
