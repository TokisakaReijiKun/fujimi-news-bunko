import io
import tempfile
import unittest
import wave
from unittest.mock import patch

from browser_tts import BROWSER_VOICES, BrowserTTS, browser_voice
from server import create_app


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((1, 2, 24000, 240, 'NONE', 'not compressed'))
        audio.writeframes(b'\x00\x00' * 240)
    return output.getvalue()


class FakeBrowserTTS:
    def __init__(self):
        self.calls = []

    def voices(self):
        return [dict(item, available=True) for item in BROWSER_VOICES]

    def synthesize(self, text, voice_id):
        self.calls.append((text, voice_id))
        return wav_bytes()


class BrowserTTSTests(unittest.TestCase):
    def test_catalog_contains_selected_kokoro_and_voicevox_styles(self):
        self.assertEqual(len(BROWSER_VOICES), 9)
        self.assertTrue(all(item['local'] is True and item['lang'] == 'ja-JP' for item in BROWSER_VOICES))
        self.assertEqual(BROWSER_VOICES[0]['id'], 'kokoro:jf_alpha')
        self.assertEqual([item['name'] for item in BROWSER_VOICES], [
            'アルファ', '春日部つむぎ', '東北イタコ', '東北ずん子', '九州そら',
            '満別花丸', '琴詠ニア', 'Voidoll', 'ナースロボ＿タイプＴ',
        ])
        self.assertEqual(
            [item['id'] for item in BROWSER_VOICES[1:]],
            ['voicevox:8', 'voicevox:109', 'voicevox:107', 'voicevox:16', 'voicevox:69',
             'voicevox:74', 'voicevox:89', 'voicevox:47'],
        )
        self.assertEqual(browser_voice('voicevox:109')['style_id'], 109)
        self.assertEqual(browser_voice('voicevox:109')['style'], 'ノーマル')

    def test_browser_voice_rejects_unknown_ids(self):
        with self.assertRaises(ValueError):
            browser_voice('voicevox:999')

    def test_browser_speech_endpoint_returns_audio_for_catalog_voice(self):
        backend = FakeBrowserTTS()
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, browser_tts_backend=backend)
            client = app.test_client()
            response = client.get('/api/browser-voices')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json), 9)
            audio = client.post('/api/browser-speech', json={
                'text': '今日は晴れです。', 'voice': 'kokoro:jf_alpha',
            })
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.mimetype, 'audio/wav')
        self.assertEqual(backend.calls, [('今日は晴れです。', 'kokoro:jf_alpha')])

    def test_browser_speech_endpoint_rejects_invalid_input(self):
        backend = FakeBrowserTTS()
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, browser_tts_backend=backend)
            client = app.test_client()
            for payload in ({'text': '', 'voice': 'kokoro:jf_alpha'},
                            {'text': '今日は晴れです。', 'voice': 'voicevox:999'},
                            {'text': 'あ' * 4001, 'voice': 'kokoro:jf_alpha'}):
                response = client.post('/api/browser-speech', json=payload)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(backend.calls, [])

    def test_local_voice_selection_is_persisted_in_browser_settings(self):
        backend = FakeBrowserTTS()
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, browser_tts_backend=backend)
            client = app.test_client()
            response = client.put('/api/settings/browser-voice', json={
                'name': 'voicevox:8', 'label': '春日部つむぎ',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['browser_voice_name'], 'voicevox:8')
            self.assertEqual(client.get('/api/settings/voice-mode').json['browser_voice_name'], 'voicevox:8')

    def test_catalog_marks_missing_runtime_as_unavailable(self):
        with patch('browser_tts.importlib.util.find_spec', return_value=None):
            voices = BrowserTTS('.').voices()
        self.assertTrue(all(not voice['available'] for voice in voices))

if __name__ == '__main__':
    unittest.main()
