import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from server import create_app, parse_epub, public_url


def fixture_epub():
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr('OEBPS/content.opf', '''<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>検証用の物語</dc:title><dc:creator>Web Test</dc:creator></metadata><manifest><item id="second" href="two.xhtml" media-type="application/xhtml+xml"/><item id="first" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="first"/><itemref idref="second"/></spine></package>''')
        z.writestr('OEBPS/one.xhtml', '<html><body><h1>第一章</h1><p>窓の外では鳥が歌っています。</p><p onclick="alert(1)">本を読んでいます。<script>alert(1)</script></p><p><a href="javascript:alert(1)">危険なリンク</a></p></body></html>')
        z.writestr('OEBPS/two.xhtml', '<html><body><h1>第二章</h1><p>新しい物語が始まります。</p></body></html>')
    return out.getvalue()


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = create_app(cls.temp.name)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        # Windows sqlite contexts commit but need explicit close before cleanup;
        # connections have no live references after gc.
        import gc
        gc.collect()
        cls.temp.cleanup()

    def wait_task(self, url):
        for _ in range(150):
            response = self.client.get(url)
            task = response.json
            if task['status'] in ('completed', 'failed', 'cancelled'):
                self.assertEqual(task['status'], 'completed', task)
                return task
            time.sleep(.03)
        self.fail('Task timeout')

    def test_boot_endpoints_and_original_assets(self):
        for url in ('/', '/static/main.js', '/static/static.css', '/static/book-reader.js', '/static/book-reader.css', '/api/health',
                    '/api/days', '/api/daily', '/api/bookmarks', '/api/books', '/api/books/tasks',
                    '/api/settings/voices', '/api/settings/voice-mode', '/api/settings/news-sources', '/api/examples',
                    '/api/settings/daily-schedule', '/api/settings/daily-content', '/api/settings/library'):
            with self.client.get(url) as response:
                self.assertEqual(response.status_code, 200, url)

    def test_reader_manual_text_import_uses_an_accessible_dialog_trigger(self):
        from bs4 import BeautifulSoup

        with self.client.get('/') as response:
            page = BeautifulSoup(response.data, 'html.parser')
        trigger = page.select_one('#open-web-text-dialog')
        dialog = page.select_one('dialog#web-text-dialog')
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.get('aria-controls'), 'web-text-dialog')
        self.assertEqual(trigger.get('aria-haspopup'), 'dialog')
        self.assertTrue(trigger.get('aria-label'))
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.get('aria-labelledby'), 'web-text-dialog-title')
        self.assertIsNotNone(dialog.select_one('form#web-text-form textarea[name="text"]'))
        self.assertEqual(dialog.select_one('#web-text-dialog-title').get_text(strip=True), 'ことばを置いて、読む時間へ。')
        picker = dialog.select_one('button#web-example-trigger')
        self.assertIsNotNone(picker)
        self.assertEqual(picker.get_text(strip=True), '填入示例')
        self.assertEqual(picker.get('aria-controls'), 'web-example-options')
        self.assertIsNotNone(dialog.select_one('input[name="voice_mode"]'))
        self.assertIsNotNone(dialog.select_one('input[name="voice_id"]'))
        self.assertIsNotNone(dialog.select_one('input[name="browser_voice_name"]'))
        article_voice = dialog.select_one('footer.web-form-actions select#web-text-voice')
        self.assertIsNotNone(article_voice)
        self.assertTrue(article_voice.has_attr('required'))
        self.assertNotIn('默认声线', article_voice.get_text())
        self.assertIsNone(dialog.select_one('.web-text-fields select#web-text-voice'))
        example_voice = page.select_one('dialog#web-example-editor select#web-example-voice')
        self.assertIsNotNone(example_voice)
        self.assertTrue(example_voice.has_attr('required'))
        self.assertNotIn('默认声线', example_voice.get_text())
        options = self.client.get('/api/examples').json
        builtins = [option for option in options if option['builtin']]
        self.assertEqual({option['title'] for option in builtins}, {'雪国（川端康成）', '読書の時間（操作示例）'})
        snow_country = next(option['text'] for option in builtins if option['title'] == '雪国（川端康成）')
        self.assertTrue(snow_country.startswith('国境の長いトンネルを抜けると雪国であった。夜の底が白くなった。信号所に汽車が止まった。'))
        self.assertIn('「駅長さん、私です、御機嫌よろしゅうございます」', snow_country)
        self.assertIn('悲しいほど美しい声であった。', snow_country)
        self.assertTrue(snow_country.rstrip().endswith('葉子は窓をしめて、赤らんだ頬に両手をあてた。'))
        self.assertGreaterEqual(len(snow_country.splitlines()), 20)
        self.assertNotIn('\n\n', snow_country)
        self.assertNotIn('&#x20;', snow_country)
        operation_example = next(option['text'] for option in builtins if option['title'] == '読書の時間（操作示例）')
        self.assertEqual(operation_example, '朝の静かな時間に、本を開きました。窓の外では、小さな鳥が歌っています。\n\n知らない言葉に出会ったら、辞書で調べてみましょう。一つの言葉から、新しい世界が広がります。\n\nこれは閲読室の使い方を確認するための例文です。実際のニュースではありません。')

    def test_reader_can_open_custom_example_editor(self):
        from bs4 import BeautifulSoup

        with self.client.get('/') as response:
            page = BeautifulSoup(response.data, 'html.parser')
        add = page.select_one('#web-example-options button#web-example-add')
        self.assertIsNotNone(add)
        self.assertEqual(add.get_text(strip=True), '增加示例')
        editor = page.select_one('dialog#web-example-editor')
        self.assertIsNotNone(editor)
        self.assertEqual(editor.get('aria-labelledby'), 'web-example-editor-title')
        self.assertIsNotNone(editor.select_one('form#web-example-form input[name="title"][required]'))
        self.assertIsNotNone(editor.select_one('form#web-example-form textarea[name="text"][required]'))
        self.assertIsNotNone(editor.select_one('[role="alert"]'))
        self.assertIsNotNone(editor.select_one('button[type="submit"]'))
        self.assertIsNotNone(editor.select_one('button#cancel-web-example-editor'))

    def test_reader_custom_examples_use_file_store_update_policy(self):
        response = self.client.post('/api/examples', json={'title': '重复示例', 'text': '第一版。'})
        self.assertEqual(response.status_code, 201)
        updated = self.client.post('/api/examples', json={'title': '重复示例', 'text': '第二版。', 'voice_mode': 'browser', 'browser_voice_name': 'Microsoft Nanami'})
        self.assertEqual(updated.status_code, 201)
        self.assertEqual(updated.json['text'], '第二版。')
        self.assertEqual(updated.json['voice_mode'], 'browser')

    def test_reader_custom_example_save_shows_success_toast(self):
        from bs4 import BeautifulSoup

        source = (Path(__file__).resolve().parents[1] / 'static' / 'main.js').read_text(encoding='utf-8')
        self.assertIn('showExampleSavedToast();', source)
        page = BeautifulSoup((Path(__file__).resolve().parents[1] / 'static' / 'index.html').read_text(encoding='utf-8'), 'html.parser')
        saved = page.select_one('#web-example-save-toast[role="status"]')
        self.assertIsNotNone(saved)
        self.assertTrue(saved.has_attr('hidden'))

    def test_dictionary_real_entries_and_romaji(self):
        self.assertEqual(self.client.get('/api/dictionary/stats').json['entries'], 159396)
        for query in ('新聞', 'しんぶん', 'shinbun', '报纸'):
            result = self.client.get('/api/dictionary/search', query_string={'q': query}).json['results']
            self.assertTrue(result, query)
        word = self.client.get('/api/dictionary/search', query_string={'q': '新聞'}).json['results'][0]
        self.assertEqual(word['spell'], '新聞')
        detail = self.client.get('/api/dictionary/words/' + word['id']).json
        self.assertTrue(detail['definitions'])
        self.assertEqual(self.client.get('/api/dictionary/words/99999999').status_code, 404)
        self.assertEqual(self.client.get('/api/dictionary/search', query_string={'q': "' OR 1=1--"}).json['results'], [])

    def test_article_bookmark_and_persistence(self):
        response = self.client.post('/api/articles/text', json={'title': '検証記事', 'text': '今日は本を読みます。\n知らない言葉を調べます。'})
        self.assertEqual(response.status_code, 201)
        a = response.json
        self.assertEqual(len(a['paragraphs']), 2)
        self.assertIn('<ruby>', a['furigana_paragraphs'][0])
        aid = a['id']
        self.client.post(f'/api/articles/{aid}/bookmarks')
        self.assertTrue(self.client.get(f'/api/articles/{aid}').json['bookmarked'])
        bookmark_root = Path(self.temp.name) / 'bookmarks'
        copies = [path for path in bookmark_root.iterdir() if path.is_dir()]
        self.assertEqual(len(copies), 1)
        self.assertEqual((copies[0] / 'original.txt').read_text(encoding='utf-8'), a['original_text'])
        self.assertTrue((copies[0] / 'furigana.html').is_file())
        self.assertTrue((copies[0] / 'media').is_dir())
        self.assertTrue((copies[0] / 'audio').is_dir())
        restored = create_app(self.temp.name).test_client()
        self.assertTrue(restored.get(f'/api/articles/{aid}').json['bookmarked'])
        self.client.delete(f'/api/articles/{aid}/bookmarks')
        self.assertFalse(self.client.get(f'/api/articles/{aid}').json['bookmarked'])
        self.assertEqual([path for path in bookmark_root.iterdir() if path.is_dir()], [])

    def test_same_example_import_reuses_same_day_article(self):
        example = self.client.get('/api/examples').json[0]
        payload = {'title': example['title'], 'text': example['text'], 'example_id': example['id'], 'voice_mode': 'browser'}
        first = self.client.post('/api/articles/text', json=payload)
        second = self.client.post('/api/articles/text', json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json['id'], second.json['id'])

    def test_repeat_example_import_with_open_article_file_does_not_replace_directory(self):
        example = self.client.get('/api/examples').json[0]
        payload = {'title': example['title'], 'text': example['text'],
                   'example_id': example['id'], 'voice_mode': 'browser'}
        first = self.client.post('/api/articles/text', json=payload)
        self.assertEqual(first.status_code, 201)
        article = self.app.article_store.load(first.json['id'])
        path = Path(self.temp.name) / 'articles' / article['_directory']
        revision = article['_revision']
        with (path / 'original.txt').open('rb') as reader:
            again = self.client.post('/api/articles/text', json=payload)
            self.assertEqual(reader.read().decode('utf-8'), article['original_text'])
        self.assertEqual(again.status_code, 201, again.json)
        self.assertEqual(again.json['id'], first.json['id'])
        self.assertTrue(path.is_dir())
        self.assertGreaterEqual(self.app.article_store.load(first.json['id'])['_revision'], revision)

    def test_missing_existing_article_folder_reports_recovery_error(self):
        import shutil
        from article_store import safe_path
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            client = app.test_client()
            example = client.get('/api/examples').json[0]
            payload = {'title': example['title'], 'text': example['text'],
                       'example_id': example['id'], 'voice_mode': 'browser'}
            first = client.post('/api/articles/text', json=payload)
            self.assertEqual(first.status_code, 201)
            article = app.article_store.load(first.json['id'])
            shutil.rmtree(safe_path(app.article_store.root, article['_directory']))
            again = client.post('/api/articles/text', json=payload)
            self.assertEqual(again.status_code, 400)
            self.assertIn('文章目录缺失', again.json['detail'])

    def test_epub_reading_order_sanitization_and_roundtrip(self):
        blob = fixture_epub()
        parsed, assets = parse_epub(blob, 'test.epub')
        self.assertEqual([c['title'] for c in parsed['chapters']], ['第一章', '第二章'])
        serialized = json.dumps(parsed)
        for forbidden in ('onclick', '<script', 'javascript:'):
            self.assertNotIn(forbidden, serialized)
        response = self.client.post('/api/books/import', data={'files': (io.BytesIO(blob), 'test.epub')}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 202)
        task = self.wait_task('/api/books/tasks/' + response.json['tasks'][0]['id'])
        bid = task['book_id']
        b = self.client.get(f'/api/books/{bid}').json
        self.assertEqual(len(b['chapters']), 2)
        payload = self.client.get(f'/api/books/{bid}/chapters/1').json
        self.assertTrue(payload['chapter']['blocks'])
        progress = self.client.put(f'/api/books/{bid}/progress', json={'chapter_id': 2, 'block_index': 1, 'language_mode': 'ja'})
        self.assertEqual(progress.json['progress']['chapter_id'], 2)
        self.client.post(f'/api/books/{bid}/chapters/1/bookmarks', json={'block_index': 1, 'excerpt': '鳥'})
        self.assertEqual(len(self.client.get(f'/api/books/{bid}').json['bookmarks']), 1)
        self.client.post(f'/api/books/{bid}/chapters/2/bookmarks', json={'block_index': 1, 'excerpt': '物語'})
        stored_book = self.client.get(f'/api/books/{bid}').json
        self.assertEqual(stored_book['bookmarks'], [{'chapter_id': 2, 'block_index': 1, 'excerpt': '物語'}])
        enhancement = self.client.post(f'/api/books/{bid}/chapters/1/enhance').json
        self.wait_task('/api/books/tasks/' + enhancement['task_id'])
        chapter = self.client.get(f'/api/books/{bid}/chapters/1').json['chapter']
        self.assertIn('ruby', chapter['blocks'][1]['furigana_html'])
        b = self.client.get(f'/api/books/{bid}').json
        self.assertEqual(b['progress']['chapter_id'], 2)
        self.assertEqual(len(b['bookmarks']), 1)
        self.client.put(f'/api/books/{bid}', json={'title': '変更後', 'series': '検証'})
        self.assertEqual(self.client.get(f'/api/books/{bid}').json['title'], '変更後')
        self.client.delete(f'/api/books/{bid}')
        self.assertEqual(self.client.get(f'/api/books/{bid}').status_code, 404)

    def test_validation_and_offline_limits(self):
        self.assertEqual(self.client.post('/api/articles/text', json={'title': '', 'text': ''}).status_code, 400)
        self.assertEqual(self.client.put('/api/settings/daily-content', json={'target_count': -1}).status_code, 400)
        self.assertEqual(self.client.put('/api/settings/daily-schedule', json={'mode': 'automatic', 'time': '99:99'}).status_code, 400)
        self.assertEqual(self.client.post('/api/articles/text', json={'title': 'x', 'text': 'x'}, headers={'Origin': 'https://example.com'}).status_code, 403)
        for url in ('file:///etc/passwd', 'http://127.0.0.1:8427/api/health', 'http://[::1]/'):
            with self.assertRaises(ValueError): public_url(url)
        aid = self.client.post('/api/articles/text', json={'title': '機能確認', 'text': '翻訳です。'}).json['id']
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(self.client.post(f'/api/articles/{aid}/retranslate').status_code, 503)
        self.assertEqual(self.client.post(f'/api/articles/{aid}/reread', json={'mode': 'voice'}).status_code, 503)

    def test_news_import_feed_and_content_extraction(self):
        import sqlite3
        with sqlite3.connect(Path(self.temp.name) / 'fujimi.sqlite3') as db:
            previous = db.execute("SELECT value FROM settings WHERE key='news-sources'").fetchone()[0]
            db.execute("UPDATE settings SET value=? WHERE key='news-sources'", (json.dumps([{'id':1,'name':'example.com','homepage':'https://example.com/rss','minimum_count':1}]),))
            db.execute("UPDATE settings SET value=? WHERE key='daily-content'", (json.dumps({'target_count':1}),))
        page = b'<html><head><title>Fixture news</title></head><body><main><h1>Fixture news</h1><p>Main article paragraph.</p><a href="/other"><p>Related article</p></a><p><a href="/other">Another recommendation</a></p></main><footer><p>Footer</p></footer></body></html>'
        feed = b'<rss><channel><item><link>https://example.com/story</link></item></channel></rss>'
        def fake_download(url):
            return (page if url == 'https://example.com/story' else feed), url
        with patch('server.download', side_effect=fake_download), patch('server.public_url', side_effect=lambda u: u), patch.dict('os.environ', {}, clear=True):
            result = self.client.post('/api/import/tasks', json={'url': 'https://example.com/story'})
            self.assertEqual(result.status_code, 202)
            task = self.wait_task('/api/import/tasks/' + result.json['task_id'])
            self.assertEqual(task['article']['paragraphs'], ['Main article paragraph.'])
            self.assertEqual(self.client.post('/api/daily/generate').json['status'], 'started')
            task = self.wait_task('/api/tasks/daily')
            self.assertGreaterEqual(task['completed'], 1)
            self.assertEqual(task['missing_sources'], [])
            day = self.client.get('/api/days').json[0]
            self.assertTrue(self.client.get('/api/daily', query_string={'date': day}).json['articles'])
        with sqlite3.connect(Path(self.temp.name) / 'fujimi.sqlite3') as db:
            db.execute("UPDATE settings SET value=? WHERE key='news-sources'", (previous,))


if __name__ == '__main__':
    unittest.main(verbosity=2)
