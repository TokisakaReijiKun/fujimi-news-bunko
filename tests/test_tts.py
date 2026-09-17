import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
import wave
from unittest.mock import patch

from article_store import ArticleStore, digest, write_json
from book_store import BookStore
from server import create_app, parse_epub
from tts_service import TTSQueue, VoiceStore, cache_key
import tts_worker
from tts_worker import split_text, segment_plan, merge_segments, segment_path, segment_manifest_path, valid_cached_segment
from test_web import fixture_epub


def wav_bytes(seconds=1, rate=48000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b'\x00\x10\x00\xf0' * (int(seconds*rate)//2))
    return output.getvalue()


class FakeBackend:
    state = 'unloaded'
    verified = False
    error = ''

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = False
        self.calls = []
        self.closed = threading.Event()

    def identity(self):
        return 'synthetic-checkpoint'

    def synthesize(self, request, directory, update, cancelled):
        self.calls.append(request['paragraphs'])
        self.entered.set()
        while not self.release.wait(.01):
            if cancelled():
                raise InterruptedError()
        if self.fail:
            raise ValueError('合成测试失败')
        total = len(request['paragraphs'])
        update(stage='tts', completed=total, total=total, message='合成测试')
        path = directory/'audio.wav'
        path.write_bytes(wav_bytes(total*.1))
        return path, {'segments': [{'duration': .1, 'speech_start_offset': 0} for _ in range(total)],
                      'sample_rate': 48000, 'completed': total, 'total': total}

    def close(self):
        self.closed.set()
        self.release.set()


class TTSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        # Bootstrap ordinary stores, then install only synthetic test voice data.
        create_app(self.data)
        self.voice = VoiceStore(self.data).save('测试声线', wav_bytes())
        db = sqlite3.connect(self.data/'fujimi.sqlite3')
        try:
            with db:
                for key, value in [('irodori-initialized-v1', True), ('voice-mode', {'mode': 'voice', 'voice_id': self.voice['id']})]:
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))
        finally:
            db.close()
        self.backend = FakeBackend()
        self.app = create_app(self.data, tts_backend=self.backend)
        self.tts = self.app.extensions['tts']
        self.client = self.app.test_client()

    def tearDown(self):
        self.tts.close()
        self.temp.cleanup()

    def wait(self, tid, status='completed'):
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            task = self.tts.queue.get(tid)
            if task['status'] not in ('queued', 'running'):
                self.assertEqual(task['status'], status, task)
                return task
            time.sleep(.01)
        self.fail('task timeout')

    def article(self):
        result = self.client.post('/api/articles/text', json={'title': '合成検証', 'text': '今日は晴れです。\n本を読みます。'})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json

    def book(self):
        blob = fixture_epub()
        parsed, assets = parse_epub(blob, 'test.epub')
        return BookStore(self.data).create(parsed, blob, assets)[0]

    def test_automatic_article_real_file_timings_and_range(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        saved = self.client.get(f"/api/articles/{article['id']}").json
        self.assertEqual(saved['audio_status'], 'ready')
        self.assertEqual(len(saved['audio_segments']), 2)
        self.assertTrue(saved['audio_path'].endswith('/audio/测试声线_合成検証.wav'))
        with self.client.get(saved['audio_path'], headers={'Range': 'bytes=0-43'}) as audio:
            self.assertEqual(audio.status_code, 206)
            self.assertTrue(audio.data.startswith(b'RIFF'))
        self.assertEqual(self.client.get(f"/api/articles/{article['id']}/assets/audio/unknown.wav").status_code, 404)

    def test_fifo_deduplication_and_cancel_retry(self):
        self.backend.release.clear()
        first = self.article()
        self.assertTrue(self.backend.entered.wait(2))
        duplicate = self.client.post(f"/api/articles/{first['id']}/tts", json={'mode': 'model'}).json
        self.assertEqual(duplicate['task_id'], first['audio_task_id'])
        second = self.article()
        self.assertEqual(len(self.backend.calls), 1)
        self.client.delete(f"/api/articles/{first['id']}/tts")
        retry = self.client.post(f"/api/articles/{first['id']}/reread", json={'mode': 'model'}).json
        self.assertNotEqual(retry['task_id'], first['audio_task_id'])
        self.backend.release.set()
        self.wait(second['audio_task_id'])
        self.wait(retry['task_id'])
        self.assertEqual(self.tts.queue.get(first['audio_task_id'])['status'], 'cancelled')
        self.assertEqual(len(self.backend.calls), 3)

    def test_cache_and_voice_version_change(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        path = f"/api/articles/{article['id']}/tts"
        cached = self.client.post(path, json={'mode': 'model'}).json
        self.assertEqual(cached['status'], 'ready')
        self.assertEqual(len(self.backend.calls), 1)
        renamed = self.client.put(f"/api/settings/voices/{self.voice['id']}", json={'name': '改名'})
        self.assertEqual(renamed.status_code, 200)
        self.voice = dict(self.voice, id=renamed.json['id'], name='改名')
        renamed_audio = self.client.post(path, json={'mode': 'model'}).json
        self.wait(renamed_audio['task_id'])
        self.assertTrue(self.client.get(f"/api/articles/{article['id']}").json['audio_path'].endswith('/audio/改名_合成検証.wav'))
        replaced = self.client.put(f"/api/settings/voices/{self.voice['id']}", data={'name': '改名', 'file': (io.BytesIO(wav_bytes(2)), 'clip.wav')})
        self.assertEqual(replaced.status_code, 200)
        new = self.client.post(path, json={'mode': 'model'}).json
        self.wait(new['task_id'])
        self.assertEqual(len(self.backend.calls), 3)

    def test_browser_selection_then_model_reuses_saved_audio(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        path = f"/api/articles/{article['id']}/tts"
        browser = self.client.post(path, json={'mode': 'browser'}).json
        self.assertEqual(browser['article']['audio_status'], 'browser')
        model = self.client.post(path, json={'mode': 'model'}).json
        self.assertEqual(model['article']['audio_status'], 'ready')
        self.assertEqual(len(self.backend.calls), 1)
        self.backend.fail = True
        other = self.tts.voices.save('別声線', wav_bytes(.5 + 1))
        failed = self.client.post(path, json={'mode': 'voice', 'voice_id': other['id']}).json
        self.wait(failed['task_id'], 'failed')
        browser = self.client.post(path, json={'mode': 'browser'}).json
        self.assertEqual(browser['article']['audio_status'], 'browser')
        self.assertNotIn('audio_task_id', browser['article'])
        model = self.client.post(path, json={'mode': 'model'}).json
        self.assertEqual(model['article']['audio_status'], 'ready')
        self.assertEqual(self.tts.queue.get(failed['task_id'])['status'], 'failed')

    def test_initialization_backs_up_settings_and_runs_once(self):
        root = self.data/'synthetic-root'
        reference = root/'Irodori-TTS/朽木冬子.mp3'
        reference.parent.mkdir(parents=True)
        reference.write_bytes(wav_bytes())
        self.tts.root = root
        before = self.tts.setting('voice-mode')
        self.tts.setting('irodori-initialized-v1', False)
        self.tts._initialize()
        marker = self.tts.setting('irodori-initialized-v1')
        backup = self.data/marker['backup']
        self.assertTrue((backup/'fujimi.sqlite3').is_file())
        self.assertEqual(json.loads((backup/'settings.json').read_text(encoding='utf-8'))['voice-mode'], before)
        self.assertTrue(all(s['voice_mode'] == 'model' for s in self.tts.setting('news-sources')))
        self.tts.setting('voice-mode', {'mode': 'browser'})
        self.tts._initialize()
        self.assertEqual(self.tts.setting('voice-mode')['mode'], 'browser')

    def test_failure_keeps_audio_and_bookmark(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        old = ArticleStore(self.data).load(article['id'])
        self.backend.fail = True
        self.client.post(f"/api/articles/{article['id']}/bookmarks")
        other = self.tts.voices.save('別声線', wav_bytes(2))
        task = self.client.post(f"/api/articles/{article['id']}/reread", json={'mode': 'voice', 'voice_id': other['id']}).json
        self.wait(task['task_id'], 'failed')
        saved = self.client.get(f"/api/articles/{article['id']}").json
        self.assertTrue(saved['bookmarked'])
        self.assertTrue(saved['audio_path'].endswith(old['audio_path']))
        self.assertEqual(saved['audio_status'], 'replace_failed')

    def test_book_merge_progress_and_audio_authorization(self):
        bid = self.book()
        self.backend.release.clear()
        task = self.client.post(f'/api/books/{bid}/chapters/1/reread', json={'mode': 'model'}).json
        self.assertTrue(self.backend.entered.wait(2))
        books = BookStore(self.data)
        books.patch_state(bid, {'progress': {'chapter_id': 1, 'block_index': 1}, 'bookmarks': [{'chapter_id': 1, 'block_index': 0}]})
        self.backend.release.set()
        self.wait(task['task_id'])
        b, ch = books.chapter(bid, 1)
        self.assertEqual(b['progress']['block_index'], 1)
        self.assertEqual(len(b['bookmarks']), 1)
        self.assertEqual(ch['audio']['status'], 'ready')
        with self.client.get(ch['audio']['url']) as audio:
            self.assertEqual(audio.status_code, 200)
        self.assertEqual(self.client.get(f'/api/books/{bid}/audio/../book.json').status_code, 404)
        path = books.audio_asset(bid, ch['audio']['path'])
        path.write_bytes(b'corrupt')
        self.assertEqual(self.client.get(ch['audio']['url']).status_code, 400)

    def test_changed_text_rejects_stale_result(self):
        self.backend.release.clear()
        article = self.article()
        self.assertTrue(self.backend.entered.wait(2))
        store = ArticleStore(self.data)
        a = store.load(article['id'])
        a['paragraphs'][0] = '内容が変更されました。'
        store.save(a)
        self.backend.release.set()
        self.wait(article['audio_task_id'], 'failed')
        self.assertFalse(store.load(article['id']).get('audio_path'))

    def test_voices_upload_url_edit_delete_and_invalid_audio(self):
        self.assertEqual(self.client.delete(f"/api/settings/voices/{self.voice['id']}").status_code, 409)
        response = self.client.post('/api/settings/voices', data={'name': '別の声', 'file': (io.BytesIO(wav_bytes()), 'clip.wav')})
        self.assertEqual(response.status_code, 200, response.json)
        vid = response.json['id']
        changed = self.client.put(f'/api/settings/voices/{vid}', json={'name': '改名'})
        self.assertEqual(changed.json['name'], '改名')
        vid = changed.json['id']
        with patch.object(self.tts, 'download', return_value=(wav_bytes(), 'https://example.com/a.wav')) as download:
            response = self.client.post('/api/settings/voices/from-url', json={'name': '网络声线', 'url': 'https://example.com/a.wav'})
            self.assertEqual(response.status_code, 200)
            download.assert_called_once_with('https://example.com/a.wav', max_bytes=20*1024*1024)
        self.assertEqual(self.client.delete(f'/api/settings/voices/{vid}').status_code, 200)
        self.assertTrue(list((self.data/'backups').glob(f'voice-{vid}-*')))
        bad = self.client.post('/api/settings/voices', data={'name': '损坏', 'file': (io.BytesIO(b'not audio'), 'clip.wav')})
        self.assertEqual(bad.status_code, 400)

    def test_voice_files_are_named_directly_without_manifest(self):
        path = self.data/'voices/测试声线.wav'
        self.assertTrue(path.is_file())
        self.assertFalse((self.data/'voices/voices.json').exists())
        self.assertLess(self.voice['id'], 2**53)
        renamed = self.client.put(f"/api/settings/voices/{self.voice['id']}", json={'name': '読み上げ'}).json
        self.assertTrue((self.data/'voices/読み上げ.wav').is_file())
        self.assertFalse(path.exists())
        mode = self.client.get('/api/settings/voice-mode').json
        self.assertEqual(mode['voice_id'], renamed['id'])
        self.assertEqual(self.client.post('/api/articles/text', json={'title': '名前の確認', 'text': 'これは確認です。'}).status_code, 201)

    def test_legacy_voice_layout_is_flattened_with_a_backup(self):
        migration = tempfile.TemporaryDirectory()
        try:
            data = Path(migration.name)
            root = data/'voices/12'
            root.mkdir(parents=True)
            old = root/'legacy.wav'
            old.write_bytes(wav_bytes())
            write_json(data/'voices/voices.json', {'next_id': 13, 'voices': [{'id': 12, 'name': '旧声线', 'file': '12/legacy.wav'}]})
            store = VoiceStore(data)
            mapping = store.migrate_legacy()
            voice = store.get(mapping[12])
            self.assertTrue((data/'voices/旧声线.wav').is_file())
            self.assertFalse((data/'voices/voices.json').exists())
            self.assertFalse(old.exists())
            self.assertTrue(list((data/'backups').glob('voice-storage-layout-*')))
            self.assertEqual(voice['name'], '旧声线')
            self.assertLess(voice['id'], 2**53)
        finally:
            migration.cleanup()

    def test_task_state_is_memory_only_and_restart_creates_no_data_tts(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        self.assertFalse((self.data/'tts').exists())
        self.tts.close()
        replacement = create_app(self.data, tts_backend=FakeBackend())
        try:
            controller = replacement.extensions['tts']
            self.assertIsNone(controller.queue.latest(f"article:{article['id']}"))
            self.assertFalse(controller.backend.calls)
            self.assertFalse((self.data/'tts').exists())
        finally:
            replacement.extensions['tts'].close()

    def test_idle_worker_release(self):
        self.tts.close()
        backend = FakeBackend()
        queue = TTSQueue(self.data/'idle', backend, lambda *a: None, idle_seconds=.03)
        try:
            self.assertTrue(backend.closed.wait(1))
        finally:
            queue.close()

    def test_split_preserves_all_text_with_token_limit(self):
        text = '長い文章、' * 300 + '。次の文です！\n末尾'
        pieces = split_text(text, lambda s: len(s)*2+1, 31)
        self.assertEqual(''.join(pieces), text)
        self.assertTrue(all(len(p)*2+1 <= 31 for p in pieces))

    def test_segment_prefix_stops_at_first_missing_or_invalid_wav(self):
        fragments = self.data/'articles/1/audio'
        fragments.mkdir(parents=True)
        plan = segment_plan(['第一段。', '第二段。', '第三段。'], lambda text: len(text), 32)
        voice = '测试声线'
        first = segment_path(fragments, voice, 0)
        first.write_bytes(wav_bytes(.2))
        third = segment_path(fragments, voice, 2)
        third.write_bytes(wav_bytes(.2))
        self.assertEqual(tts_worker.resumable_segment_prefix(plan, fragments, voice), [first])
        first.write_bytes(first.read_bytes()[:20])
        self.assertEqual(tts_worker.resumable_segment_prefix(plan, fragments, voice), [])

    def test_segment_filenames_are_clear_and_ordered(self):
        fragments = self.data/'articles/1/audio'
        fragments.mkdir(parents=True)
        first = segment_path(fragments, '浅倉透', 0)
        first.write_bytes(wav_bytes(.2))
        self.assertTrue(valid_cached_segment(first, ''))
        self.assertEqual(first.name, '浅倉透_segment_01.wav')
        other = segment_path(fragments, '浅倉透', 1)
        self.assertEqual(other.name, '浅倉透_segment_02.wav')
        self.assertFalse(other.exists())

    def test_existing_contiguous_segments_resume_without_manifest(self):
        self.assertTrue(hasattr(tts_worker, 'resumable_segment_prefix'),
                        'worker must resume directly from numbered WAV files')
        fragments = self.data/'articles/1/audio'
        fragments.mkdir(parents=True)
        voice = '朽木冬子'
        first = segment_path(fragments, voice, 0)
        second = segment_path(fragments, voice, 1)
        first.write_bytes(wav_bytes(.1))
        second.write_bytes(wav_bytes(.2))
        plan = segment_plan(['第一段。', '第二段。', '第三段。'], len, 256)
        reused = tts_worker.resumable_segment_prefix(plan, fragments, voice)
        self.assertEqual(reused, [first, second])
        self.assertFalse(segment_manifest_path(fragments, voice).exists())

    def test_successful_commit_removes_voice_segments_and_manifest(self):
        self.backend.release.clear()
        article = self.article()
        self.assertTrue(self.backend.entered.wait(2))
        stored = self.tts.articles.load(article['id'])
        audio = self.tts.articles.root/stored['_directory']/'audio'
        for index in range(2):
            segment_path(audio, self.voice['name'], index).write_bytes(wav_bytes(.1))
        segment_manifest_path(audio, self.voice['name']).write_text('{}', encoding='utf-8')
        self.backend.release.set()
        self.wait(article['audio_task_id'])
        self.assertFalse(list(audio.glob(f"{self.voice['name']}_segment_*.wav")))
        self.assertFalse(segment_manifest_path(audio, self.voice['name']).exists())

    def test_paragraphs_remain_whole_until_token_budget_exceeded(self):
        text = '第一文。第二文！第三文？\n末尾。'
        self.assertEqual(split_text(text, len, 256), [text])
        self.assertEqual(split_text('字'*256, len, 512), ['字'*256])
        self.assertGreater(len(split_text('字'*257, len, 512)), 1)
        # The user limit is tokens, not Unicode character count.
        self.assertEqual(split_text('字'*400, lambda s: (len(s)+1)//2, 512), ['字'*400])
        self.assertGreater(len(split_text(text, len, 8)), 1)
        plan = segment_plan([text, '短段。'], len, 256)
        self.assertEqual([p['paragraph_index'] for p in plan], [0, 1])

    def test_merge_stream_preserves_pcm_order_and_paragraph_timings(self):
        paths = [self.data/f'segment-{i}.wav' for i in range(3)]
        expected = b''
        for i, path in enumerate(paths):
            with wave.open(str(path), 'wb') as audio:
                audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                pcm = bytes([i+1, 0]) * (4800*(i+1))
                audio.writeframes(pcm)
                expected += pcm
        target = self.data/'merged.wav'
        timeline = merge_segments([{'paragraph_index': i} for i in (0, 0, 1)], paths, 2, target)
        self.assertEqual([v['duration'] for v in timeline], [.3, .3])
        with wave.open(str(target), 'rb') as audio:
            self.assertEqual(audio.readframes(audio.getnframes()), expected)
        before = target.read_bytes()
        with self.assertRaises(InterruptedError):
            merge_segments([{'paragraph_index': 0}], paths[:1], 1, target, lambda: True)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(target.with_suffix('.tmp').exists())

    def test_same_voice_reused_on_reread_force_and_model_change(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        with patch.object(self.backend, 'identity', side_effect=AssertionError('must not load model')):
            response = self.client.post(f"/api/articles/{article['id']}/reread", json={'mode': 'model', 'force': True})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['status'], 'ready')
        self.assertEqual(len(self.backend.calls), 1)

    def test_same_voice_reuse_while_windows_audio_response_is_open(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        saved = self.client.get(f"/api/articles/{article['id']}").json
        stream = self.client.get(saved['audio_path'], headers={'Range':'bytes=0-1023'}, buffered=False)
        try:
            self.assertTrue(next(iter(stream.response)).startswith(b'RIFF'))
            response = self.client.post(f"/api/articles/{article['id']}/reread", json={'mode':'model'})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json['status'], 'ready')
        finally:
            stream.close()
        self.assertEqual(len(self.backend.calls), 1)

    def test_switch_voice_back_reuses_article_and_chapter(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        bid = self.book()
        book_url = f'/api/books/{bid}/chapters/1/reread'
        first_book = self.client.post(book_url, json={'mode': 'model'}).json
        self.wait(first_book['task_id'])
        other = self.tts.voices.save('別声線', wav_bytes(2))
        article_url = f"/api/articles/{article['id']}/reread"
        for url in (article_url, book_url):
            task = self.client.post(url, json={'mode': 'voice', 'voice_id': other['id']}).json
            self.wait(task['task_id'])
        self.assertEqual(len(self.backend.calls), 4)
        for url in (article_url, book_url):
            response = self.client.post(url, json={'mode': 'model', 'force': True})
            self.assertEqual(response.json['status'], 'ready', response.json)
        self.assertEqual(len(self.backend.calls), 4)
        self.assertEqual(self.tts.articles.load(article['id'])['audio_voice_id'], self.voice['id'])
        self.assertEqual(self.tts.books.chapter(bid, 1)[1]['audio']['voice_id'], self.voice['id'])

    def test_changed_text_and_corrupt_audio_do_not_reuse(self):
        article = self.article()
        self.wait(article['audio_task_id'])
        store = self.tts.articles
        a = store.load(article['id'])
        a['paragraphs'][0] = '新しい原文です。'
        store.save(a)
        url = f"/api/articles/{article['id']}/tts"
        self.wait(self.client.post(url, json={'mode': 'model'}).json['task_id'])
        a = store.load(article['id'])
        store.asset(a['id'], a['audio_path']).write_bytes(b'corrupt')
        self.wait(self.client.post(url, json={'mode': 'model'}).json['task_id'])
        self.assertEqual(len(self.backend.calls), 3)

    def test_missing_obsolete_audio_is_backed_up_and_does_not_block_commit(self):
        self.backend.release.clear()
        article = self.article()
        self.assertTrue(self.backend.entered.wait(2))
        store = self.tts.articles
        a = store.load(article['id'])
        old = self.data/'old.wav'
        old.write_bytes(wav_bytes())
        a['_assets'].append({'path': 'audio/old.wav', 'kind': 'audio'})
        a = store.save(a, files={'audio/old.wav': old})
        store.asset(a['id'], 'audio/old.wav').unlink()
        self.backend.release.set()
        self.wait(article['audio_task_id'])
        saved = store.load(a['id'])
        self.assertNotIn('audio/old.wav', [v['path'] for v in saved['_assets']])
        backups = list((self.data/'backups').glob(f"tts-article-{a['id']}-*"))
        self.assertEqual(len(backups), 1)
        original = json.loads((backups[0]/'article/article.json').read_text(encoding='utf-8'))
        self.assertIn('audio/old.wav', [v['path'] for v in original['assets']])
        self.assertTrue((backups[0]/'fujimi.sqlite3').is_file())

    def test_tts_uses_no_persistent_runtime_folder_after_success_or_failure(self):
        # Create before patching so initial news storage is outside this assertion.
        self.backend.release.clear()
        article = self.article()
        self.assertTrue(self.backend.entered.wait(2))
        self.backend.release.set()
        self.wait(article['audio_task_id'])
        self.assertFalse((self.data/'diagnostics/tts-tasks').exists())
        self.assertFalse((self.data/'tts').exists())
        other = self.tts.voices.save('別声線', wav_bytes(2))
        with patch.object(self.tts.queue, 'commit', side_effect=OSError('save failed')):
            task = self.client.post(f"/api/articles/{article['id']}/tts", json={'mode': 'voice', 'voice_id': other['id']}).json
            self.wait(task['task_id'], 'failed')
        self.assertFalse((self.data/'tts').exists())


if __name__ == '__main__':
    unittest.main()
