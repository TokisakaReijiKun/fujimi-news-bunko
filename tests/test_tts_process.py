"""Worker initialization errors must reach the UI through ready.json."""
import builtins
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tts_worker


class WorkerInitializationTests(unittest.TestCase):
    def test_torch_import_commit_limit_is_reported_without_raw_dll_details(self):
        original_import = builtins.__import__

        def fail_torch(name, *args, **kwargs):
            if name == 'torch':
                error = OSError('Error loading PRIVATE_PATH/nvperf_host.dll')
                error.winerror = 1455
                raise error
            return original_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            arguments = ['tts_worker.py', '--workspace', directory,
                         '--model', str(workspace / 'model/model.safetensors')]
            with patch('sys.argv', arguments), patch('threading.Thread'), \
                    patch('builtins.__import__', fail_torch):
                with self.assertRaises(OSError):
                    tts_worker.main()
            result_path = workspace / 'ready.json'
            self.assertTrue(result_path.is_file(), 'Import errors must complete the error handshake')
            error = json.loads(result_path.read_text(encoding='utf-8'))['error']
            self.assertIn('1455', error)
            self.assertIn('虚拟内存', error)
            self.assertNotIn('PRIVATE_PATH', error)


if __name__ == '__main__':
    unittest.main()
