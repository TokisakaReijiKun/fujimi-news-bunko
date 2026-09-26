"""Windows window host for the existing local Web application."""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import sys
import threading

from local_config import load_local_config
from server import ROOT, create_app, make_local_server

DESKTOP_PORT = 8428


def resolve_data_dir(resource_root, *, frozen, environ, executable=None):
    configured = environ.get('FUJIMI_DATA_DIR')
    if configured:
        return Path(configured).expanduser()
    if frozen:
        binary = Path(executable or sys.executable).resolve()
        if binary.parent.parent.name.lower() == 'dist':
            project = binary.parents[2]
            if (project / 'server.py').is_file() and (project / 'data' / 'fujimi.sqlite3').is_file():
                return project / 'data'
        local = environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        return Path(local) / 'FujimiShinbunBunko' / 'data'
    return Path(resource_root) / 'data'


def runtime_logs_dir(data_dir, resource_root):
    data_dir = Path(data_dir)
    return Path(resource_root) / 'logs' if data_dir == Path(resource_root) / 'data' else data_dir / 'logs'


def find_tts_runtime(data_dir, *, executable=None, environ=None):
    environ = os.environ if environ is None else environ
    binary = Path(executable or sys.executable).resolve()
    projects = [Path(data_dir).resolve().parent]
    if binary.parent.parent.name.lower() == 'dist':
        projects.append(binary.parents[2])
    project = next((root for root in projects
                    if (root / 'tts_worker.py').is_file()
                    and (root / 'Irodori-TTS/model/model.safetensors').is_file()), None)
    if project is None:
        return None
    configured = environ.get('FUJIMI_TTS_PYTHON')
    candidates = ([Path(configured).expanduser()] if configured else [
        Path('D:/Anaconda/envs/Tokyo/python.exe'),
        Path.home() / 'Anaconda3/envs/Tokyo/python.exe',
    ])
    python = next((path for path in candidates if path.is_file()), None)
    return (project, python) if python else None


class DesktopBridge:
    def __init__(self, resource_root, data_dir, logs_dir, opener=None):
        self.resource_root = Path(resource_root)
        self.data_dir = Path(data_dir)
        self.logs_dir = Path(logs_dir)
        self.opener = opener or os.startfile

    def get_desktop_settings(self):
        return {
            'project_root': str(self.resource_root),
            'data_dir': str(self.data_dir),
            'python_executable': sys.executable,
        }

    def _open_folder(self, path):
        path.mkdir(parents=True, exist_ok=True)
        self.opener(str(path))
        return {'ok': True}

    def open_data_dir(self):
        return self._open_folder(self.data_dir)

    def open_log_dir(self):
        return self._open_folder(self.logs_dir)


class DesktopWindowLifecycle:
    def __init__(self, window, confirm_exit):
        self.window = window
        self.confirm_exit = confirm_exit
        self.exiting = False

    def on_close(self):
        if self.exiting:
            return True
        self.window.hide()
        return False

    def show_window(self, *_args):
        self.window.show()

    def quit(self, *_args):
        if self.exiting or not self.confirm_exit():
            return
        self.exiting = True
        try:
            self.window.destroy()
        except Exception:
            self.exiting = False
            raise


def create_tray_icon(lifecycle):
    import pystray
    from PIL import Image

    image = Image.open(ROOT / 'assets' / 'desktop-icon.png').convert('RGBA')
    menu = pystray.Menu(
        pystray.MenuItem('打开窗口', lifecycle.show_window, default=True),
        pystray.MenuItem('退出', lifecycle.quit),
    )
    return pystray.Icon('fujimi-shinbun-bunko', image, '富士見新聞文庫', menu=menu)


def _active_tasks(app):
    with app.test_client() as client:
        response = client.get('/api/runtime/tasks')
        if response.status_code != 200:
            return False
        tasks = response.get_json().get('tasks', [])
    return any(task.get('status') in {
        'queued', 'running', 'starting', 'processing', 'collecting',
        'enhancing', 'media', 'cancelling',
    } for task in tasks)


def _confirm_close(app):
    if not _active_tasks(app):
        return True
    answer = ctypes.windll.user32.MessageBoxW(
        None, '还有日刊、导入、翻译或朗读任务在运行。现在退出会中断任务，确定退出吗？',
        '富士見新聞文庫', 0x04 | 0x30,
    )
    return answer == 6


def run_desktop(*, data_dir=None, webview_module=None, tray_factory=None,
                enable_tts=None, port=DESKTOP_PORT):
    if os.name != 'nt':
        raise RuntimeError('桌面客户端仅支持 Windows。')
    frozen = bool(getattr(sys, 'frozen', False))
    data_dir = Path(data_dir) if data_dir is not None else resolve_data_dir(ROOT, frozen=frozen, environ=os.environ)
    logs_dir = runtime_logs_dir(data_dir, ROOT)
    logs_dir.mkdir(parents=True, exist_ok=True)
    load_local_config(data_dir.parent if frozen else ROOT)

    if webview_module is None:
        import webview
        webview_module = webview

    app = None
    http_server = make_local_server(lambda environ, start_response: app(environ, start_response), '127.0.0.1', port)
    thread = None
    scheduler_thread = None
    tray = None
    tray_started = False
    scheduler_stop = threading.Event()
    pid_file = logs_dir / 'desktop.pid'
    try:
        tts_runtime = find_tts_runtime(data_dir) if frozen and enable_tts is not False else None
        tts_enabled = (bool(tts_runtime) if frozen else True) if enable_tts is None else enable_tts
        tts_backend = None
        tts_root = None
        if frozen and tts_enabled:
            if not tts_runtime:
                raise RuntimeError('未找到项目 Irodori 模型或 Tokyo Python；请检查 FUJIMI_TTS_PYTHON。')
            from tts_service import ProcessBackend
            tts_root, python = tts_runtime
            tts_backend = ProcessBackend(tts_root, data_dir, python_executable=python)
        app = create_app(data_dir, enable_tts=tts_enabled, tts_backend=tts_backend, tts_root=tts_root)
        from desktop_edge_speech import register_edge_speech
        register_edge_speech(app)
        pid_file.write_text(str(os.getpid()), encoding='utf-8')
        thread = threading.Thread(target=http_server.serve_forever, name='fujimi-desktop-http', daemon=True)
        thread.start()
        scheduler_thread = threading.Thread(
            target=app.fujimi_scheduler, args=(scheduler_stop,),
            name='fujimi-desktop-scheduler', daemon=True,
        )
        scheduler_thread.start()

        url = f'http://127.0.0.1:{http_server.server_port}/?desktop=1'
        bridge = DesktopBridge(Path(sys.executable).resolve().parent if frozen else ROOT,
                               data_dir, logs_dir)
        window = webview_module.create_window(
            '富士見新聞文庫', url, js_api=bridge, width=1280, height=820,
            min_size=(900, 620), text_select=True,
        )
        lifecycle = DesktopWindowLifecycle(window, lambda: _confirm_close(app))
        window.events.closing += lifecycle.on_close
        tray = (tray_factory or create_tray_icon)(lifecycle)
        tray.run_detached()
        tray_started = True
        profile = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'FujimiShinbunBunko' / 'webview'
        profile.mkdir(parents=True, exist_ok=True)
        webview_module.start(gui='edgechromium', private_mode=False, storage_path=str(profile))
    finally:
        if tray_started:
            tray.stop()
        scheduler_stop.set()
        if scheduler_thread is not None:
            scheduler_thread.join(timeout=5)
        if thread is not None:
            http_server.shutdown()
            thread.join(timeout=5)
        http_server.server_close()
        if app is not None:
            app.extensions['tts'].close()
            app.extensions['browser_tts'].close()
        if pid_file.exists() and pid_file.read_text(encoding='utf-8').strip() == str(os.getpid()):
            pid_file.unlink()


def main():
    parser = argparse.ArgumentParser(description='富士見新聞文庫 Windows 桌面客户端')
    parser.add_argument('--port', type=int, default=DESKTOP_PORT)
    args = parser.parse_args()
    try:
        run_desktop(port=args.port)
    except (Exception, SystemExit) as error:
        ctypes.windll.user32.MessageBoxW(
            None, f'桌面应用启动失败：{error}', '富士見新聞文庫', 0x10,
        )
        raise


if __name__ == '__main__':
    main()
