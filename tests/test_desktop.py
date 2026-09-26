import tempfile
import threading
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urljoin
from urllib.request import urlopen

import desktop


class DesktopTests(unittest.TestCase):
    def test_close_hides_window_and_tray_exit_stops_it(self):
        class Window:
            def __init__(self):
                self.hidden = False
                self.destroyed = False
                self.shown = False

            def hide(self):
                self.hidden = True

            def show(self):
                self.hidden = False
                self.shown = True

            def restore(self):
                pass

            def destroy(self):
                self.destroyed = True

        window = Window()
        lifecycle = desktop.DesktopWindowLifecycle(window, lambda: True)
        self.assertFalse(lifecycle.on_close())
        self.assertTrue(window.hidden)
        self.assertFalse(window.destroyed)

        lifecycle.show_window()
        self.assertTrue(window.shown)
        self.assertFalse(window.hidden)

        lifecycle.quit()
        self.assertTrue(window.destroyed)
        self.assertTrue(lifecycle.on_close())

    def test_tray_exit_can_keep_running_task_alive(self):
        class Window:
            destroyed = False

            def destroy(self):
                self.destroyed = True

        window = Window()
        lifecycle = desktop.DesktopWindowLifecycle(window, lambda: False)
        lifecycle.quit()
        self.assertFalse(window.destroyed)

    def test_command_line_defaults_to_desktop_port(self):
        with patch.object(sys, 'argv', ['desktop.py']), patch.object(desktop, 'run_desktop') as launch:
            desktop.main()
        launch.assert_called_once_with(port=8428)

    def test_packaged_data_uses_local_app_data_unless_overridden(self):
        root = Path('C:/application')
        local = {'LOCALAPPDATA': 'C:/Users/Test/AppData/Local'}
        self.assertEqual(
            desktop.resolve_data_dir(root, frozen=True, environ=local),
            Path('C:/Users/Test/AppData/Local/FujimiShinbunBunko/data'),
        )
        self.assertEqual(
            desktop.resolve_data_dir(root, frozen=True, environ={**local, 'FUJIMI_DATA_DIR': 'D:/文庫'}),
            Path('D:/文庫'),
        )
        self.assertEqual(desktop.resolve_data_dir(root, frozen=False, environ={}), root / 'data')

    def test_packaged_app_in_project_uses_existing_web_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / 'server.py').touch()
            (project / 'data').mkdir()
            (project / 'data' / 'fujimi.sqlite3').touch()
            executable = project / 'dist' / 'FujimiShinbunBunko' / 'FujimiShinbunBunko.exe'
            local = {'LOCALAPPDATA': str(project / 'local')}

            self.assertEqual(
                desktop.resolve_data_dir(project / '_internal', frozen=True, environ=local,
                                         executable=executable),
                project / 'data',
            )
            self.assertEqual(
                desktop.resolve_data_dir(project / '_internal', frozen=True,
                                         environ={**local, 'FUJIMI_DATA_DIR': str(project / 'other')},
                                         executable=executable),
                project / 'other',
            )
            self.assertEqual(
                desktop.resolve_data_dir(project / '_internal', frozen=True, environ=local,
                                         executable=project / 'download' / 'FujimiShinbunBunko.exe'),
                project / 'local' / 'FujimiShinbunBunko' / 'data',
            )

    def test_packaged_tts_runtime_uses_project_model_and_tokyo_python(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            model = project / 'Irodori-TTS' / 'model' / 'model.safetensors'
            model.parent.mkdir(parents=True)
            model.touch()
            (project / 'tts_worker.py').touch()
            tokyo = project / 'Tokyo' / 'python.exe'
            tokyo.parent.mkdir()
            tokyo.touch()
            executable = project / 'dist' / 'FujimiShinbunBunko' / 'FujimiShinbunBunko.exe'
            runtime = desktop.find_tts_runtime(project / 'data', executable=executable,
                                               environ={'FUJIMI_TTS_PYTHON': str(tokyo)})
            self.assertEqual(runtime, (project, tokyo))
            self.assertIsNone(desktop.find_tts_runtime(project / 'data', executable=executable,
                                                        environ={'FUJIMI_TTS_PYTHON': str(project / 'missing.exe')}))

    def test_bridge_opens_only_its_configured_folders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            opened = []
            bridge = desktop.DesktopBridge(root, root / 'data', root / 'logs', opened.append)
            settings = bridge.get_desktop_settings()
            self.assertEqual(settings['data_dir'], str(root / 'data'))
            self.assertEqual(settings['project_root'], str(root))
            self.assertTrue(bridge.open_data_dir()['ok'])
            self.assertTrue(bridge.open_log_dir()['ok'])
            self.assertEqual(opened, [str(root / 'data'), str(root / 'logs')])
            self.assertTrue((root / 'data').is_dir())
            self.assertTrue((root / 'logs').is_dir())

    def test_window_serves_real_app_and_closes_its_server(self):
        class WindowEvents:
            def __init__(self):
                self.closing = self

            def __iadd__(self, callback):
                self.callback = callback
                return self

        class Window:
            def __init__(self):
                self.events = WindowEvents()
                self.hidden = False

            def hide(self):
                self.hidden = True

            def show(self):
                self.hidden = False

            def restore(self):
                pass

            def destroy(self):
                self.events.closing.callback()

        class Tray:
            def __init__(self, lifecycle):
                self.lifecycle = lifecycle
                self.started = False
                self.stopped = False

            def run_detached(self):
                self.started = True

            def stop(self):
                self.stopped = True

        class Webview:
            def __init__(self):
                self.url = None
                self.window = Window()

            def create_window(self, title, url, **kwargs):
                self.url = url
                self.bridge = kwargs['js_api']
                return self.window

            def start(self, **kwargs):
                self.start_options = kwargs
                with urlopen(urljoin(self.url, 'api/health'), timeout=10) as response:
                    self.health = response.read().decode('utf-8')
                with urlopen(self.url, timeout=10) as response:
                    self.html = response.read().decode('utf-8')
                self.close_cancelled = self.window.events.closing.callback() is False
                self.hidden_after_close = self.window.hidden
                with urlopen(urljoin(self.url, 'api/health'), timeout=10) as response:
                    self.health_while_hidden = response.status
                tray.lifecycle.show_window()
                self.restored = not self.window.hidden
                tray.lifecycle.quit()

        with tempfile.TemporaryDirectory() as temporary:
            webview = Webview()
            tray = None

            def make_tray(lifecycle):
                nonlocal tray
                tray = Tray(lifecycle)
                return tray

            logs = Path(temporary) / 'logs'
            logs.mkdir()
            (logs / 'server.pid').write_text('existing-web-process', encoding='utf-8')
            with patch.object(desktop, 'load_local_config'):
                desktop.run_desktop(data_dir=Path(temporary), webview_module=webview,
                                    tray_factory=make_tray, enable_tts=False, port=0)
            self.assertIn('"status":"ok"', webview.health)
            self.assertIn('富士見新聞文庫', webview.html)
            self.assertIn('?desktop=1', webview.url)
            self.assertTrue(webview.close_cancelled)
            self.assertTrue(webview.hidden_after_close)
            self.assertEqual(webview.health_while_hidden, 200)
            self.assertTrue(webview.restored)
            self.assertTrue(tray.started)
            self.assertTrue(tray.stopped)
            self.assertFalse(webview.start_options['private_mode'])
            self.assertTrue(Path(webview.start_options['storage_path']).is_absolute())
            self.assertEqual(webview.bridge.get_desktop_settings()['data_dir'], temporary)
            self.assertFalse(any(t.name == 'fujimi-desktop-scheduler' and t.is_alive()
                                 for t in threading.enumerate()))
            self.assertEqual((logs / 'server.pid').read_text(encoding='utf-8'), 'existing-web-process')
            self.assertFalse((logs / 'desktop.pid').exists())
            with self.assertRaises(OSError):
                urlopen(urljoin(webview.url, 'api/health'), timeout=1)


if __name__ == '__main__':
    unittest.main()
