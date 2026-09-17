from pathlib import Path
import unittest

from tts_worker import runtime_options, sampling_options


class RuntimeConfigurationTests(unittest.TestCase):
    def test_web_uses_local_codec_on_same_gpu_in_bfloat16(self):
        model = Path('example/model/model.safetensors')
        options = runtime_options(model)
        self.assertEqual(options['model_device'], 'cuda:0')
        self.assertEqual(options['codec_device'], 'cuda:0')
        self.assertEqual(options['model_precision'], 'bf16')
        self.assertEqual(options['codec_precision'], 'bf16')
        self.assertEqual(Path(options['codec_repo']), model.parent/'Semantic-DACVAE-Japanese-32dim/weights.pth')

    def test_sampling_matches_successful_script(self):
        options = sampling_options('第一文。第二文。', 'voice.wav', 42)
        self.assertEqual(options, dict(text='第一文。第二文。', ref_wav='voice.wav',
            no_ref=False, num_steps=40, cfg_scale_text=3.0, cfg_scale_speaker=5.0,
            max_seconds=30.0, seed=42))
