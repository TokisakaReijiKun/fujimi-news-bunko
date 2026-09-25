"""Exercise the worker protocol with real, lightweight Tokyo subprocesses."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from tts_service import ProcessBackend


WORKER = '''
import argparse, json, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--workspace')
p.add_argument('--model')
a = p.parse_args()
w = Path(a.workspace)
counter = Path('attempts')
n = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(n))
(w/'loading.json').write_text(json.dumps({'stage': 'codec'}))
mode = Path('mode').read_text()
if mode == 'crash' or (mode == 'recover' and n == 1):
    raise SystemExit(17)
if mode == 'error':
    (w/'ready.json').write_text(json.dumps({'error': 'invalid model'}))
else:
    (w/'ready.json').write_text(json.dumps({'ready': True}))
while True:
    request_path = w/'request.json'
    if mode == 'synthesize' and request_path.exists():
        job = Path(json.loads(request_path.read_text())['directory'])
        request_path.unlink()
        (job/'progress.json').write_text(json.dumps({'stage': 'tts', 'completed': 1, 'total': 1}))
        time.sleep(.6)
        (job/'audio.wav').write_bytes(b'synthetic audio')
        (job/'result.json').write_text(json.dumps({'completed': 1, 'total': 1}))
    time.sleep(.1)
'''


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'tts_worker.py').write_text(WORKER, encoding='utf-8')
        self.backend = ProcessBackend(self.root, self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.backend.close)

    def start(self, mode):
        (self.root/'mode').write_text(mode)
        self.backend._start(lambda **kw: None, lambda: False)

    def test_native_exit_retries_once_then_reuses_ready_worker(self):
        self.start('recover')
        pid = self.backend.process.pid
        self.backend._start(lambda **kw: None, lambda: False)
        self.assertEqual(self.backend.process.pid, pid)
        self.assertEqual((self.root/'attempts').read_text(), '2')
        self.assertEqual(self.backend.state, 'ready')

    def test_repeated_crash_is_bounded_and_reports_exit_and_stage(self):
        with self.assertRaisesRegex(RuntimeError, '17.*codec'):
            self.start('crash')
        self.assertEqual((self.root/'attempts').read_text(), '2')
        self.assertIsNone(self.backend.process)
        self.assertIsNone(self.backend.workspace)

    def test_reported_model_error_is_not_retried(self):
        with self.assertRaisesRegex(RuntimeError, 'invalid model'):
            self.start('error')
        self.assertEqual((self.root/'attempts').read_text(), '1')

    def test_cancel_does_not_launch_worker(self):
        with self.assertRaises(InterruptedError):
            self.backend._start(lambda **kw: None, lambda: True)
        self.assertFalse((self.root/'attempts').exists())

    def test_progress_read_sharing_violation_does_not_kill_worker(self):
        (self.root/'mode').write_text('synthesize')
        job = self.root/'job'
        job.mkdir()
        original = Path.read_text
        blocked = []
        def read(path, *args, **kwargs):
            if path.name == 'progress.json' and not blocked:
                blocked.append(path)
                raise PermissionError(13, 'temporary sharing violation', str(path))
            return original(path, *args, **kwargs)
        progress = []
        with patch.object(Path, 'read_text', read):
            output, result = self.backend.synthesize({}, job, lambda **v: progress.append(v), lambda: False)
        self.assertTrue(blocked)
        self.assertEqual(output.read_bytes(), b'synthetic audio')
        self.assertEqual(result['completed'], 1)
        self.assertEqual(self.backend.state, 'ready')
        self.assertIsNone(self.backend.process.poll())

    def test_progress_publication_retries_replacement_and_keeps_complete_json(self):
        from tts_protocol import write_json
        import os
        path = self.root/'progress.json'
        path.write_text('{"completed":0}')
        replace = os.replace
        attempts = []
        def locked_then_available(source, destination):
            attempts.append(1)
            if len(attempts) < 3:
                self.assertEqual(json.loads(path.read_text())['completed'], 0)
                raise PermissionError(13, 'temporary sharing violation')
            return replace(source, destination)
        with patch('tts_protocol.os.replace', locked_then_available):
            write_json(path, {'completed': 1})
        self.assertEqual(json.loads(path.read_text()), {'completed': 1})
        self.assertEqual(list(self.root.glob('progress.json.*.tmp')), [])

    def test_permanent_permission_error_is_bounded_and_preserves_previous_progress(self):
        from tts_protocol import write_json
        path = self.root/'progress.json'
        path.write_text('{"completed":0}')
        with patch('tts_protocol.os.replace', side_effect=PermissionError(13, 'denied')) as replace:
            with self.assertRaises(PermissionError):
                write_json(path, {'completed': 1})
        self.assertLessEqual(replace.call_count, 8)
        self.assertEqual(json.loads(path.read_text()), {'completed': 0})
        self.assertEqual(list(self.root.glob('progress.json.*.tmp')), [])
