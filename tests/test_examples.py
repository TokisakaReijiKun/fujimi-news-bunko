import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import patch
from example_store import ExampleStore

from server import create_app


class ExampleStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_builtin_examples_are_seeded_as_files(self):
        response = self.client.get('/api/examples')
        self.assertEqual(response.status_code, 200)
        examples = response.json
        self.assertEqual({item['title'] for item in examples}, {'雪国（川端康成）', '読書の時間（操作示例）'})
        root = Path(self.temp.name) / 'articles' / 'examples'
        for item in examples:
            folder = root / item['directory']
            self.assertTrue((folder / 'example.json').is_file())
            self.assertTrue((folder / 'original.txt').is_file())
            manifest = json.loads((folder / 'example.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['title'], item['title'])
            self.assertEqual((folder / 'original.txt').read_text(encoding='utf-8'), item['text'])

    def test_example_translation_is_saved_as_translation_file(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only'}, clear=False), patch('server.translate', return_value=['第一段译文。']):
            response = self.client.post('/api/examples', json={'title': '带译文示例', 'text': '第一段。'})
        self.assertEqual(response.status_code, 201)
        item = response.json
        folder = Path(self.temp.name) / 'articles' / 'examples' / item['directory']
        self.assertEqual((folder / 'translation.txt').read_text(encoding='utf-8'), '第一段译文。')
        self.assertEqual(item['translated_paragraphs'], ['第一段译文。'])

    def test_example_audio_is_saved_under_example_directory(self):
        item = self.app.extensions['examples'].create('带音频示例', '本文。')
        source = Path(self.temp.name) / 'sample.wav'
        source.write_bytes(b'wav')
        saved = self.app.extensions['examples'].save_audio(item['id'], 7, source, {'text_sha256': 'abc', 'voice_name': '测试声线'})
        self.assertTrue((Path(self.temp.name) / 'articles' / 'examples' / saved['directory'] / 'audio').is_dir())
        self.assertEqual(saved['audio_versions'][0]['voice_id'], 7)
        self.assertEqual(saved['audio_versions'][0]['path'], 'audio/测试声线_带音频示例.wav')

    def test_existing_example_translation_is_reused_without_translation_request(self):
        first = self.client.post('/api/examples', json={'title': '已有译文示例', 'text': '第一段。', 'voice_mode': 'browser'})
        self.assertEqual(first.status_code, 201)
        self.app.extensions['examples'].save_translation(first.json['id'], ['第一段译文。'])
        with patch('server.translate', side_effect=AssertionError('translation should be reused')):
            response = self.client.post('/api/articles/text', json={
                'title': first.json['title'], 'text': first.json['text'], 'example_id': first.json['id'], 'voice_mode': 'browser'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['translated_paragraphs'], ['第一段译文。'])

    def test_custom_example_is_saved_with_voice_metadata(self):
        response = self.client.post('/api/examples', json={
            'title': '测试例文',
            'text': '今日は声線を選んで読みます。',
            'voice_mode': 'browser',
            'browser_voice_name': 'Haruka',
        })
        self.assertEqual(response.status_code, 201)
        item = response.json
        self.assertEqual(item['title'], '测试例文')
        self.assertEqual(item['voice_mode'], 'browser')
        self.assertEqual(item['browser_voice_name'], 'Haruka')
        manifest = json.loads((Path(self.temp.name) / 'articles' / 'examples' / item['directory'] / 'example.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['browser_voice_name'], 'Haruka')

        updated = self.client.post('/api/examples', json={
            'title': '测试例文', 'text': '更新后的正文。', 'voice_mode': 'browser',
            'browser_voice_name': 'Microsoft Nanami',
        })
        self.assertEqual(updated.status_code, 201)
        self.assertEqual(updated.json['voice_mode'], 'browser')
        self.assertEqual((Path(self.temp.name) / 'articles' / 'examples' / updated.json['directory'] / 'original.txt').read_text(encoding='utf-8'), '更新后的正文。')
        self.assertTrue(list((Path(self.temp.name) / 'backups').glob('example-*')))

    def test_example_directory_uses_readable_title(self):
        item = self.client.post('/api/examples', json={'title': '我的阅读示例：第一篇', 'text': '本文。'}).json
        self.assertEqual(item['directory'], '我的阅读示例：第一篇')
        self.assertTrue((Path(self.temp.name) / 'articles' / 'examples' / '我的阅读示例：第一篇' / 'example.json').is_file())

    def test_legacy_examples_move_to_articles_examples_with_backup(self):
        legacy = Path(self.temp.name) / 'examples' / 'custom-old'
        legacy.mkdir(parents=True)
        (legacy / 'example.json').write_text(json.dumps({'schema_version': 1, 'id': 'custom-old', 'title': '旧示例', 'voice_mode': 'inherit', 'voice_id': None, 'browser_voice_name': '', 'builtin': False}), encoding='utf-8')
        (legacy / 'original.txt').write_text('旧正文。', encoding='utf-8')
        app = create_app(self.temp.name)
        result = app.test_client().get('/api/examples')
        self.assertIn('旧示例', [item['title'] for item in result.json])
        self.assertTrue((Path(self.temp.name) / 'articles' / 'examples' / '旧示例' / 'original.txt').is_file())
        self.assertTrue(list((Path(self.temp.name) / 'backups').glob('examples-migration-*')))
        self.assertFalse((Path(self.temp.name) / 'examples').exists())

    def test_text_import_keeps_example_voice_choice_for_reading(self):
        response = self.client.post('/api/articles/text', json={
            'title': '带声线的示例',
            'text': '本文使用浏览器声线。',
            'voice_mode': 'browser',
            'browser_voice_name': 'Microsoft Nanami Online',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['example_voice_mode'], 'browser')
        self.assertEqual(response.json['example_browser_voice_name'], 'Microsoft Nanami Online')

    def test_example_import_is_scoped_to_day_and_reuses_translation(self):
        item = self.app.extensions['examples'].create('日付検証', '本文。', translated_paragraphs=['正文。'])
        payload = dict(title=item['title'], text=item['text'], example_id=item['id'], voice_mode='browser')
        with patch('server.translate', side_effect=AssertionError('cached translation requested again')):
            with patch('server.now', return_value='2026-09-25T12:00:00+08:00'):
                first = self.client.post('/api/articles/text', json=payload).json
                repeat = self.client.post('/api/articles/text', json=payload).json
            with patch('server.now', return_value='2026-09-26T12:00:00+08:00'):
                next_day = self.client.post('/api/articles/text', json=payload).json
        self.assertEqual(first['id'], repeat['id'])
        self.assertNotEqual(first['id'], next_day['id'])
        self.assertEqual(next_day['translated_paragraphs'], ['正文。'])

    def test_changed_example_payload_cannot_reuse_cached_translation(self):
        item = self.app.extensions['examples'].create('変更検証', '元の本文。', translated_paragraphs=['原正文。'])
        before = self.app.article_store.ids()
        result = self.client.post('/api/articles/text', json={
            'title': item['title'], 'text': '別の本文。', 'example_id': item['id'], 'voice_mode': 'browser'})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.app.article_store.ids(), before)

    def test_invalid_voice_never_creates_article(self):
        before = self.app.article_store.ids()
        for voice in ({'voice_mode': 'wrong'}, {'voice_mode': 'voice', 'voice_id': 7}):
            response = self.client.post('/api/articles/text', json={'title': '无效声线', 'text': '本文。', **voice})
            self.assertGreaterEqual(response.status_code, 400)
            self.assertEqual(self.app.article_store.ids(), before)

    def test_failed_example_update_preserves_old_files(self):
        store = self.app.extensions['examples']
        item = store.create('保留', '原始正文。')
        with patch('example_store.write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                store.create('保留', '新正文。')
        self.assertEqual(next(x for x in store.list() if x['id'] == item['id'])['text'], '原始正文。')

    @unittest.skipUnless(os.name == 'nt', 'Windows directory sharing semantics')
    def test_open_example_file_does_not_block_translation_commit(self):
        store = self.app.extensions['examples']
        item = store.create('占用时更新', '原始正文。')
        folder = Path(self.temp.name) / 'articles' / 'examples' / item['directory']
        with (folder / 'original.txt').open('rb') as reader:
            updated = store.save_translation(item['id'], ['第一段译文。'])
            self.assertEqual(reader.read().decode('utf-8'), '原始正文。')
        self.assertEqual(updated['translated_paragraphs'], ['第一段译文。'])
        self.assertEqual((folder / 'translation.txt').read_text(encoding='utf-8'), '第一段译文。')
        self.assertEqual(store.get(item['id'])['text'], '原始正文。')

    @unittest.skipUnless(os.name == 'nt', 'Windows directory sharing semantics')
    def test_open_cached_audio_does_not_block_other_voice_registration(self):
        store = self.app.extensions['examples']
        item = store.create('音频占用时更新', '本文。')
        audio = Path(self.temp.name) / 'voice.wav'
        audio.write_bytes(b'synthetic wav bytes')
        store.save_audio(item['id'], 3, audio, {'voice_name': '声线甲', 'text_sha256': 'first'})
        folder = Path(self.temp.name) / 'articles' / 'examples' / item['directory']
        first = folder / 'audio' / '声线甲_音频占用时更新.wav'
        with first.open('rb') as reader:
            updated = store.save_audio(item['id'], 4, audio, {'voice_name': '声线乙', 'text_sha256': 'second'})
            self.assertEqual(reader.read(), b'synthetic wav bytes')
        self.assertEqual({part['voice_id'] for part in updated['audio_versions']}, {3, 4})
        self.assertTrue(first.is_file())

    def test_interrupted_manifest_commit_restores_original_example(self):
        from example_store import replace_transaction_directory
        store = self.app.extensions['examples']
        original = store.create('可恢复更新', '旧正文。', translated_paragraphs=['旧译文。'])
        folder = Path(self.temp.name) / 'articles' / 'examples' / original['directory']
        failed = False
        def fail_manifest_once(source, destination):
            nonlocal failed
            if destination.name == 'example.json' and not failed:
                failed = True
                raise PermissionError(13, 'transient lock', str(destination))
            return replace_transaction_directory(source, destination)
        with patch('example_store.replace_transaction_directory', fail_manifest_once):
            with self.assertRaises(PermissionError):
                store.create('可恢复更新', '新正文。', translated_paragraphs=['新译文。'])
        self.assertTrue(failed)
        self.assertEqual(store.get(original['id'])['text'], '旧正文。')
        self.assertEqual((folder / 'translation.txt').read_text(encoding='utf-8'), '旧译文。')
        self.assertTrue(list((Path(self.temp.name) / 'backups').glob('example-*')))

    def test_open_previous_voice_can_be_replaced_with_distinct_audio_version(self):
        store = self.app.extensions['examples']
        example = store.create('声线换版', '本文。')
        first = Path(self.temp.name) / 'first.wav'
        second = Path(self.temp.name) / 'second.wav'
        first.write_bytes(b'first audio')
        second.write_bytes(b'second audio')
        original = store.save_audio(example['id'], 7, first, {'voice_name': '同名声线', 'text_sha256': 'first'})
        folder = Path(self.temp.name) / 'articles' / 'examples' / original['directory']
        old_path = folder / original['audio_versions'][0]['path']
        with old_path.open('rb') as reader:
            updated = store.save_audio(example['id'], 7, second, {'voice_name': '同名声线', 'text_sha256': 'second'})
            self.assertEqual(reader.read(), b'first audio')
        self.assertNotEqual(updated['audio_versions'][0]['path'], original['audio_versions'][0]['path'])
        self.assertEqual((folder / updated['audio_versions'][0]['path']).read_bytes(), b'second audio')

    @unittest.skipUnless(os.name == 'nt', 'Windows file-sharing semantics')
    def test_blocked_file_update_recovers_after_reader_closes(self):
        store = self.app.extensions['examples']
        item = store.create('句柄占用恢复', '之前的正文。')
        folder = Path(self.temp.name) / 'articles' / 'examples' / item['directory']
        with (folder / 'original.txt').open('rb') as reader:
            with self.assertRaises(PermissionError):
                store.create('句柄占用恢复', '新的正文。')
            self.assertEqual(reader.read().decode('utf-8'), '之前的正文。')
        self.assertEqual(store.get(item['id'])['text'], '之前的正文。')
        self.assertEqual(list(folder.glob('*.tmp')), [])
        self.assertEqual(list(store.transactions.glob('*/journal.json')), [])

    def test_browser_migration_is_backed_up_and_idempotent(self):
        payload = {'examples': [{'title': '旧浏览器示例', 'text': '元の文章。'}]}
        for _ in range(2):
            response = self.client.post('/api/examples/migrate', json=payload)
            self.assertEqual(response.status_code, 200, response.json)
        items = self.client.get('/api/examples').json
        self.assertEqual(sum(x['title'] == '旧浏览器示例' for x in items), 1)
        self.assertTrue(list((Path(self.temp.name) / 'backups').glob('examples-browser-*.json')))
        self.client.post('/api/examples', json={'title': '旧浏览器示例', 'text': '更新後。'})
        self.client.post('/api/examples/migrate', json=payload)
        self.assertEqual(next(x for x in self.client.get('/api/examples').json if x['title'] == '旧浏览器示例')['text'], '更新後。')

    def test_builtin_can_keep_custom_voice_without_reseeding(self):
        item = self.client.get('/api/examples').json[0]
        result = self.client.post('/api/examples', json={**item, 'voice_mode': 'browser', 'browser_voice_name': 'Haruka'})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(ExampleStore(self.temp.name).list()[0]['browser_voice_name'], 'Haruka')

    def test_damaged_example_is_reported_not_overwritten(self):
        root = Path(self.temp.name) / 'articles' / 'examples' / '雪国（川端康成）'
        (root / 'original.txt').unlink()
        response = self.client.get('/api/examples')
        self.assertGreaterEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
