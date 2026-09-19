"""Exercise the worker protocol with real, lightweight Tokyo subprocesses."""
from pathlib import Path
import tempfile
import unittest

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
