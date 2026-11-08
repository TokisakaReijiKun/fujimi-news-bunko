"""Checkpoint loading must work without Windows copy-on-write mappings."""
import json
import inspect
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Irodori-TTS'))


class CheckpointLoadingTests(unittest.TestCase):
    def test_windows_loads_weights_and_metadata_without_copy_on_write(self):
        import torch
        from safetensors import safe_open
        from safetensors.torch import load_file, save_file
        from irodori_tts import inference_runtime as runtime

        if 'backend' not in inspect.signature(load_file).parameters:
            self.skipTest('pread requires Safetensors 0.8 or newer')

        def limited_open(*args, **kwargs):
            if kwargs.get('backend', 'mmap') == 'mmap':
                raise OSError('页面文件太小，无法完成操作。 (os error 1455)')
            return safe_open(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.safetensors'
            save_file({'weight': torch.tensor([1.0, 2.0])}, path,
                      metadata={'config_json': json.dumps({'latent_dim': 32, 'max_text_len': 256})})
            with patch('sys.platform', 'win32'), \
                    patch.object(runtime, 'safe_open', limited_open), \
                    patch('safetensors.torch.safe_open', limited_open):
                state, config, inference, encoder = runtime._load_checkpoint_from_safetensors(path)
            self.assertEqual(state['weight'].tolist(), [1.0, 2.0])
            self.assertEqual(config, {'latent_dim': 32})
            self.assertEqual(inference, {'max_text_len': 256})
            self.assertIsNone(encoder)


if __name__ == '__main__':
    unittest.main()
