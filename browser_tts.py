"""Local Kokoro and VOICEVOX voices used by browser speech playback."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
from pathlib import Path
import threading


MAX_TEXT = 4000

_VOICEVOX_STYLES = (
    ('voicevox:8', '春日部つむぎ', 'ノーマル', 8, '0.vvm'),
    ('voicevox:109', '東北イタコ', 'ノーマル', 109, '21.vvm'),
    ('voicevox:107', '東北ずん子', 'ノーマル', 107, '21.vvm'),
    ('voicevox:16', '九州そら', 'ノーマル', 16, '2.vvm'),
    ('voicevox:69', '満別花丸', 'ノーマル', 69, '14.vvm'),
    ('voicevox:74', '琴詠ニア', 'ノーマル', 74, '14.vvm'),
    ('voicevox:89', 'Voidoll', 'ノーマル', 89, '17.vvm'),
    ('voicevox:47', 'ナースロボ＿タイプＴ', 'ノーマル', 47, '11.vvm'),
)

BROWSER_VOICES = (
    {'id': 'kokoro:jf_alpha', 'provider': 'kokoro', 'name': 'アルファ',
     'voice': 'jf_alpha', 'lang': 'ja-JP', 'local': True},
    *(
        {'id': voice_id, 'provider': 'voicevox', 'name': character,
         'character': character, 'style': style, 'style_id': style_id, 'model': model,
         'lang': 'ja-JP', 'local': True}
        for voice_id, character, style, style_id, model in _VOICEVOX_STYLES
    ),
)
_VOICE_BY_ID = {voice['id']: voice for voice in BROWSER_VOICES}


def browser_voice(voice_id):
    voice = _VOICE_BY_ID.get(str(voice_id or ''))
    if voice is None:
        raise ValueError('请选择有效的本地浏览器声线。')
    return deepcopy(voice)


class BrowserTTS:
    """Lazy, process-local model wrapper; model files remain outside web assets."""

    def __init__(self, root):
        self.root = Path(root)
        self.kokoro_root = self.root / 'Irodori-TTS' / 'model' / 'Kokoro'
        self.voicevox_root = self.root / 'Irodori-TTS' / 'model' / 'VOICEVOX'
        self.lock = threading.RLock()
        self._kokoro_pipeline = None
        self._voicevox_runtime = None
        self._voicevox_synthesizer = None
        self._voicevox_model = None
        self._voicevox_model_path = None

    def voices(self):
        result = []
        for voice in BROWSER_VOICES:
            item = deepcopy(voice)
            item['available'] = self._available(item)
            result.append(item)
        return result

    def _available(self, voice):
        if voice['provider'] == 'kokoro':
            return importlib.util.find_spec('kokoro') is not None and all((self.kokoro_root / relative).is_file() for relative in (
                'config.json', 'kokoro-v1_0.pth', f"voices/{voice['voice']}.pt"))
        return (importlib.util.find_spec('voicevox_core') is not None
                and (self.voicevox_root / 'dict/open_jtalk_dic_utf_8-1.11').is_dir()
                and bool(list((self.voicevox_root / 'onnxruntime/lib').glob('*.dll')))
                and (self.voicevox_root / 'models/vvms' / voice['model']).is_file())

    def synthesize(self, text, voice_id):
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError('正文须为 1–4000 字。')
        voice = browser_voice(voice_id)
        if not self._available(voice):
            raise RuntimeError(f"本地声线资源不可用：{voice['name']}")
        with self.lock:
            if voice['provider'] == 'kokoro':
                return self._synthesize_kokoro(text, voice)
            return self._synthesize_voicevox(text, voice)

    def _synthesize_kokoro(self, text, voice):
        import numpy as np
        import soundfile as sf
        import torch
        from kokoro import KModel, KPipeline

        if self._kokoro_pipeline is None:
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            model = KModel(
                repo_id='hexgrad/Kokoro-82M',
                config=str(self.kokoro_root / 'config.json'),
                model=str(self.kokoro_root / 'kokoro-v1_0.pth'),
            ).to(device).eval()
            self._kokoro_pipeline = KPipeline(
                lang_code='j', repo_id='hexgrad/Kokoro-82M', model=model, device=device,
            )
        chunks = []
        voice_file = self.kokoro_root / 'voices' / f"{voice['voice']}.pt"
        with torch.inference_mode():
            for result in self._kokoro_pipeline(text, voice=str(voice_file)):
                if result.audio is not None:
                    chunks.append(result.audio.detach().cpu().numpy())
        if not chunks:
            raise RuntimeError('Kokoro 没有生成音频。')
        output = io.BytesIO()
        sf.write(output, np.concatenate(chunks), 24000, format='WAV', subtype='PCM_16')
        return output.getvalue()

    def _voicevox_synthesizer_for(self, voice):
        from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

        model_path = self.voicevox_root / 'models' / 'vvms' / voice['model']
        if self._voicevox_synthesizer is None:
            runtime = self.voicevox_root / 'onnxruntime' / 'lib' / Onnxruntime.LIB_RECOMMENDED_VERSIONED_FILENAME
            self._voicevox_runtime = Onnxruntime.load_once(filename=str(runtime))
            dictionary = self.voicevox_root / 'dict' / 'open_jtalk_dic_utf_8-1.11'
            self._voicevox_synthesizer = Synthesizer(
                self._voicevox_runtime, OpenJtalk(dictionary), acceleration_mode='CPU')
        if self._voicevox_model_path != model_path:
            if self._voicevox_model is not None:
                self._voicevox_synthesizer.unload_voice_model(self._voicevox_model.id)
                self._voicevox_model.close()
            self._voicevox_model = VoiceModelFile.open(model_path)
            self._voicevox_synthesizer.load_voice_model(self._voicevox_model)
            self._voicevox_model_path = model_path
        return self._voicevox_synthesizer

    def _synthesize_voicevox(self, text, voice):
        return self._voicevox_synthesizer_for(voice).tts(text, voice['style_id'])

    def close(self):
        with self.lock:
            if self._voicevox_synthesizer is not None and self._voicevox_model is not None:
                self._voicevox_synthesizer.unload_voice_model(self._voicevox_model.id)
                self._voicevox_model.close()
            self._voicevox_model = None
            self._voicevox_model_path = None
            self._voicevox_synthesizer = None
            self._voicevox_runtime = None
            self._kokoro_pipeline = None
