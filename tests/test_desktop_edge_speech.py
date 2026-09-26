import tempfile
import unittest
from unittest.mock import patch
import hashlib

from server import create_app
from desktop_edge_speech import _edge_filename, register_edge_speech, synthesize_with_segments


class DesktopEdgeSpeechTests(unittest.TestCase):
    def test_paragraph_timing_uses_next_paragraph_first_sentence_offset(self):
        paragraphs = ['短い。一文続く。', 'とても長い次の段落。']
        chunks = [
            {'type': 'audio', 'data': b'ID3synthetic'},
            {'type': 'SentenceBoundary', 'offset': 1_000_000, 'duration': 10_000_000, 'text': '短い。'},
            {'type': 'SentenceBoundary', 'offset': 11_000_000, 'duration': 24_000_000, 'text': '一文続く。'},
            {'type': 'SentenceBoundary', 'offset': 35_000_000, 'duration': 40_000_000,
             'text': 'とても長い次の段落。'},
        ]

        class FakeCommunicate:
            async def stream(self):
                for chunk in chunks:
                    yield chunk

        with patch('edge_tts.Communicate', return_value=FakeCommunicate()):
            audio, segments = synthesize_with_segments('\n'.join(paragraphs),
                                                      'ja-JP-KeitaNeural', paragraphs)
        self.assertEqual(audio, b'ID3synthetic')
        self.assertEqual(segments, [
            {'duration': 3.5, 'speech_start_offset': 0.1, 'timing_source': 'edge_sentence'},
            {'duration': 4.0, 'speech_start_offset': 0, 'timing_source': 'edge_sentence'},
        ])

    def test_duplicate_sentences_are_matched_in_paragraph_order(self):
        paragraphs = ['同じ文。続き。', '同じ文。次の話。']
        chunks = [
            {'type': 'audio', 'data': b'ID3synthetic'},
            {'type': 'SentenceBoundary', 'offset': 1_000_000, 'duration': 10_000_000, 'text': '同じ文。'},
            {'type': 'SentenceBoundary', 'offset': 11_000_000, 'duration': 10_000_000, 'text': '続き。'},
            {'type': 'SentenceBoundary', 'offset': 21_000_000, 'duration': 10_000_000, 'text': '同じ文。'},
            {'type': 'SentenceBoundary', 'offset': 31_000_000, 'duration': 10_000_000, 'text': '次の話。'},
        ]

        class FakeCommunicate:
            async def stream(self):
                for chunk in chunks:
                    yield chunk

        with patch('edge_tts.Communicate', return_value=FakeCommunicate()):
            _, segments = synthesize_with_segments('\n'.join(paragraphs),
                                                  'ja-JP-KeitaNeural', paragraphs)
        self.assertAlmostEqual(segments[0]['duration'], 2.1)
        self.assertAlmostEqual(segments[1]['duration'], 2.0)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name)
        register_edge_speech(self.app)
        self.client = self.app.test_client()

    def test_only_supported_voices_generate_audio(self):
        with patch('desktop_edge_speech.synthesize', return_value=b'ID3synthetic') as synthesize:
            response = self.client.post('/api/desktop/edge-speech', json={
                'text': '今日は晴れです。', 'voice': 'ja-JP-KeitaNeural',
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'audio/mpeg')
        self.assertEqual(response.data, b'ID3synthetic')
        synthesize.assert_called_once_with('今日は晴れです。', 'ja-JP-KeitaNeural')

    def test_rejects_unknown_voice_and_oversized_text_without_contacting_service(self):
        with patch('desktop_edge_speech.synthesize') as synthesize:
            for body in ({'text': 'こんにちは', 'voice': 'en-US-AriaNeural'},
                         {'text': 'あ' * 4001, 'voice': 'ja-JP-NanamiNeural'},
                         {'text': '', 'voice': 'ja-JP-NanamiNeural'}):
                self.assertEqual(self.client.post('/api/desktop/edge-speech', json=body).status_code, 400)
        synthesize.assert_not_called()

    def test_article_generation_saves_mp3_under_article_audio(self):
        article = self.client.post('/api/articles/text', json={
            'title': '在线声线保存', 'text': '今日は晴れです。', 'voice_mode': 'none',
        }).get_json()
        with patch('desktop_edge_speech.synthesize_with_segments', return_value=(
                b'ID3saved', [{'duration': 1.2, 'speech_start_offset': 0}])):
            response = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                        json={'voice': 'ja-JP-KeitaNeural'})
        self.assertEqual(response.status_code, 200, response.get_json())
        saved = self.client.get(f"/api/articles/{article['id']}").get_json()
        self.assertEqual(saved['audio_status'], 'ready')
        self.assertEqual(saved['audio_voice_mode'], 'browser')
        self.assertTrue(saved['audio_path'].endswith('.mp3'))
        with self.client.get(saved['audio_path']) as audio:
            self.assertEqual(audio.data, b'ID3saved')
        self.assertFalse([asset for asset in self.app.article_store.load(article['id'])['_assets']
                          if asset['path'].startswith('audio/')])

    def test_repeated_online_generation_reuses_saved_mp3(self):
        article = self.client.post('/api/articles/text', json={
            'title': '在线声线复用', 'text': '今日は晴れです。', 'voice_mode': 'none',
        }).get_json()
        with patch('desktop_edge_speech.synthesize_with_segments', return_value=(
                b'ID3saved', [{'duration': 1.2, 'speech_start_offset': 0,
                               'timing_source': 'edge_sentence'}])) as synthesize:
            first = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                     json={'voice': 'ja-JP-KeitaNeural'}).get_json()
            second = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                      json={'voice': 'ja-JP-KeitaNeural'}).get_json()
        self.assertEqual(first['article']['audio_path'], second['article']['audio_path'])
        self.assertTrue(second['cached'])
        synthesize.assert_called_once()

    def test_legacy_online_audio_is_regenerated_with_precise_timing(self):
        article = self.client.post('/api/articles/text', json={
            'title': '旧音频时间轴', 'text': '最初の段落。\n次の段落。', 'voice_mode': 'none',
        }).get_json()
        legacy = [{'duration': 1.2, 'speech_start_offset': 0},
                  {'duration': 1.2, 'speech_start_offset': 0}]
        precise = [{'duration': 1.0, 'speech_start_offset': 0.1, 'timing_source': 'edge_sentence'},
                   {'duration': 1.4, 'speech_start_offset': 0, 'timing_source': 'edge_sentence'}]
        with patch('desktop_edge_speech.synthesize_with_segments', side_effect=[
                (b'ID3legacy', legacy), (b'ID3precise', precise)]) as synthesize:
            first = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                     json={'voice': 'ja-JP-KeitaNeural'}).get_json()
            second = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                      json={'voice': 'ja-JP-KeitaNeural'}).get_json()
            third = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                     json={'voice': 'ja-JP-KeitaNeural'}).get_json()
        self.assertNotEqual(first['article']['audio_path'], second['article']['audio_path'])
        self.assertNotIn('cached', second)
        self.assertEqual(second['article']['audio_segments'], precise)
        self.assertTrue(third['cached'])
        self.assertEqual(synthesize.call_count, 2)

    def test_numeric_legacy_segments_are_regenerated(self):
        article = self.client.post('/api/articles/text', json={
            'title': '旧格式音频', 'text': '最初の段落。', 'voice_mode': 'none',
        }).get_json()
        current = self.app.article_store.load(article['id'])
        folder = self.app.article_store.root / current['_directory']
        old_path = 'audio/圭太_旧格式音频.mp3'
        (folder / old_path).write_bytes(b'ID3legacy')
        current.update(audio_path=old_path, audio_segments=[1.2], audio_status='ready',
                       audio_voice_mode='browser', audio_voice_name='ja-JP-KeitaNeural')
        self.app.article_store.save_tts(current)
        precise = [{'duration': 1.2, 'speech_start_offset': 0.1,
                    'timing_source': 'edge_sentence'}]
        with patch('desktop_edge_speech.synthesize_with_segments', return_value=(b'ID3precise', precise)):
            response = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                        json={'voice': 'ja-JP-KeitaNeural'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['article']['audio_segments'], precise)

    def test_existing_audio_without_timing_is_preserved_when_regenerated(self):
        article = self.client.post('/api/articles/text', json={
            'title': '同名音频', 'text': '今日は晴れです。', 'voice_mode': 'none',
        }).get_json()
        current = self.app.article_store.load(article['id'])
        folder = self.app.article_store.root / current['_directory'] / 'audio'
        filename = _edge_filename(current['title'], '圭太')
        stem = f"{filename[:-4]}-{hashlib.sha256('ja-JP-KeitaNeural'.encode()).hexdigest()[:8]}"
        (folder / filename).write_bytes(b'previous')
        (folder / f'{stem}.mp3').write_bytes(b'previous duplicate')
        with patch('desktop_edge_speech.synthesize_with_segments', return_value=(
                b'ID3precise', [{'duration': 1.2, 'speech_start_offset': 0.1,
                                 'timing_source': 'edge_sentence'}])) as synthesize:
            response = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                        json={'voice': 'ja-JP-KeitaNeural'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotIn('cached', response.get_json())
        self.assertNotEqual(response.get_json()['article']['audio_path'].split('/')[-1], filename)
        self.assertEqual((folder / filename).read_bytes(), b'previous')
        synthesize.assert_called_once()

    def test_online_audio_preserves_existing_audio_for_later_reuse(self):
        article = self.client.post('/api/articles/text', json={
            'title': '保留已有声线', 'text': '今日は晴れです。', 'voice_mode': 'none',
        }).get_json()
        store = self.app.article_store
        current = store.load(article['id'])
        old_path = 'audio/朽木冬子_保留已有声线.wav'
        folder = store.root / current['_directory']
        (folder / old_path).write_bytes(b'RIFFold')
        current['_assets'].append({'path': old_path, 'kind': 'audio', 'tts': {
            'voice_id': 123, 'voice_sha256': 'voice', 'text_sha256': 'text',
            'segments': [{'duration': 1.0, 'speech_start_offset': 0}],
        }})
        current.update(audio_path=old_path, audio_status='ready', audio_voice_mode='voice', audio_voice_id=123)
        store.save_tts(current)
        with patch('desktop_edge_speech.synthesize_with_segments', return_value=(
                b'ID3online', [{'duration': 1.2, 'speech_start_offset': 0}])):
            response = self.client.post(f"/api/articles/{article['id']}/edge-tts",
                                        json={'voice': 'ja-JP-KeitaNeural'})
        self.assertEqual(response.status_code, 200, response.get_json())
        refreshed = store.load(article['id'])
        self.assertTrue((folder / old_path).is_file())
        self.assertFalse([item for item in refreshed['_assets'] if item['path'].startswith('audio/')])
        self.assertNotEqual(refreshed['audio_path'], old_path)
