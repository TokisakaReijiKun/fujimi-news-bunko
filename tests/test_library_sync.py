"""Real file-store transfers; all libraries live in temporary directories."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from bs4 import BeautifulSoup

from article_store import ArticleStore, digest
from book_store import BookStore
from example_store import ExampleStore


class LibrarySyncTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('library_sync'), 'Library transfer is not implemented.')
        from library_sync import LibrarySync
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stores = []
        self.sync = []
        for name in ('pc', 'phone'):
            article = ArticleStore(self.root / name)
            book = BookStore(self.root / name)
            example = ExampleStore(self.root / name, article)
            self.stores.append((article, book, example))
            self.sync.append(LibrarySync(article, book, example))

    def article(self, side=0, **changes):
        payload = dict(title='朝のニュース', url='https://example.test/news/1',
                       paragraphs=['日本語の本文。'], translated_paragraphs=[], furigana_paragraphs=[],
                       created_at='2026-10-17T10:00:00+08:00', status='ready')
        payload.update(changes)
        return self.stores[side][0].create(payload, '2026-10-17')

    def bundle(self, kind, side=0, title=None):
        items = self.sync[side].manifest()['items']
        item = next(x for x in items if x['kind'] == kind and (title is None or x['title'] == title))
        return self.sync[side].export_bundle(item['key'])

    def test_article_transfers_media_audio_and_bookmark_with_local_id(self):
        self.article(1, url='https://example.test/different')
        image = self.root / 'image.png'; image.write_bytes(b'PNG fixture')
        audio = self.root / 'voice.mp3'; audio.write_bytes(b'ID3 fixture')
        article = self.article()
        article.update(translated_paragraphs=['中文正文。'], image_paths=['media/photo.png'],
                       _assets=[dict(path='media/photo.png', kind='image')], audio_path='audio/七海.mp3')
        article = self.stores[0][0].save(article, files={'media/photo.png': image, 'audio/七海.mp3': audio})
        self.stores[0][0].set_bookmarked(article['id'], True)
        folder = self.stores[0][0].root / article['_directory']
        (folder / 'audio' / 'voice_segment_0001.wav').write_bytes(b'incomplete')
        archive = self.bundle('article')
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertNotIn('files/audio/voice_segment_0001.wav', z.namelist())
        result = self.sync[1].import_bundle(archive, expected_sha256=digest(archive))
        self.assertEqual(result['status'], 'created')
        saved = self.stores[1][0].load(result['id'])
        self.assertNotEqual(saved['id'], article['id'])
        self.assertEqual(saved['translated_paragraphs'], ['中文正文。'])
        self.assertEqual(self.stores[1][0].asset(saved['id'], 'media/photo.png').read_bytes(), b'PNG fixture')
        self.assertEqual(self.stores[1][0].asset(saved['id'], 'audio/七海.mp3').read_bytes(), b'ID3 fixture')
        self.assertTrue(saved['bookmarked'])
        self.assertTrue(any(self.stores[1][0].bookmarks.glob('*/article.json')))
        self.assertEqual(self.sync[1].import_bundle(archive)['status'], 'unchanged')

    def test_missing_translation_is_filled_but_progress_and_existing_text_remain(self):
        source = self.article(translated_paragraphs=['中文正文。'], progress={'offset': 0})
        target = self.article(1, progress={'offset': 8})
        result = self.sync[1].import_bundle(self.bundle('article'))
        self.assertEqual(result['status'], 'updated')
        saved = self.stores[1][0].load(target['id'])
        self.assertEqual(saved['progress'], {'offset': 8})
        self.assertEqual(saved['translated_paragraphs'], ['中文正文。'])
        source['paragraphs'] = ['被修改的正文。']
        self.stores[0][0].save(source)
        result = self.sync[1].import_bundle(self.bundle('article'))
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(self.stores[1][0].load(target['id'])['paragraphs'], ['日本語の本文。'])
        self.assertTrue(list((self.stores[1][0].data / 'backups').glob('sync-article-*')))

    def test_existing_bookmark_copy_receives_new_translation(self):
        self.article(translated_paragraphs=['中文正文。'])
        local = self.article(1)
        self.stores[1][0].set_bookmarked(local['id'], True)
        result = self.sync[1].import_bundle(self.bundle('article'))
        self.assertEqual(result['status'], 'updated')
        copy = next(self.stores[1][0].bookmarks.glob('*/translation.txt'))
        self.assertEqual(copy.read_text(encoding='utf-8'), '中文正文。')

    def test_partial_translation_merge_updates_whole_translation(self):
        self.article(paragraphs=['一。', '二。'], translated_paragraphs=['', '第二段。'])
        local = self.article(1, paragraphs=['一。', '二。'], translated_paragraphs=['第一段。', ''])
        self.assertEqual(self.sync[1].import_bundle(self.bundle('article'))['status'], 'updated')
        saved = self.stores[1][0].load(local['id'])
        self.assertEqual(saved['translated_paragraphs'], ['第一段。', '第二段。'])
        self.assertEqual(saved['full_translation'], '第一段。\n\n第二段。')

    def test_book_and_example_round_trip_with_real_resources(self):
        book = dict(title='本の題名', author='著者', original_filename='原本.epub',
                    chapters=[dict(id=1, title='第一章', blocks=[dict(id=1, text_ja='本の本文。', text_zh='书的正文。')])],
                    progress={'chapter_id': 1, 'offset': 42}, bookmarks=[{'chapter_id': 1, 'block_index': 0}])
        bid, _ = self.stores[0][1].create(book, b'EPUB fixture', {'cover.png': b'cover'})
        voice = self.root / 'book.wav'; voice.write_bytes(b'RIFF book fixture')
        saved = self.stores[0][1].load(bid)
        self.stores[0][1].save(saved, audio_files={'七海.wav': voice})
        result = self.sync[1].import_bundle(self.bundle('book'))
        self.assertEqual(result['status'], 'created')
        saved = self.stores[1][1].load(result['id'])
        self.assertEqual(saved['chapters'][0]['blocks'][0]['text_zh'], '书的正文。')
        self.assertEqual(saved['progress'], {})
        self.assertEqual(self.stores[1][1].asset(result['id'], 'cover.png').read_bytes(), b'cover')
        self.assertEqual(self.stores[1][1].audio_asset(result['id'], '七海.wav').read_bytes(), b'RIFF book fixture')
        self.assertEqual(self.sync[1].import_bundle(self.bundle('book'))['status'], 'unchanged')
        example = self.stores[1][2].create('自定义示例', '日本語。', translated_paragraphs=['中文。'])
        self.stores[1][2].save_audio(example['id'], None, voice, {'voice_name': '七海', 'text_sha256': digest('日本語。'.encode())})
        result = self.sync[0].import_bundle(self.bundle('example', 1, '自定义示例'))
        self.assertEqual(result['status'], 'created')
        saved_example = self.stores[0][2].get(result['id'])
        self.assertEqual(saved_example['translated_paragraphs'], ['中文。'])
        self.assertEqual((self.stores[0][2].root / saved_example['directory'] / saved_example['audio_versions'][0]['path']).read_bytes(), b'RIFF book fixture')

    def test_imported_book_audio_uses_remapped_local_book_id(self):
        book = dict(title='朗读书籍', original_filename='book.epub', chapters=[dict(id=1, title='章节', blocks=[dict(id=1, text_ja='本文。')])])
        self.stores[1][1].create(dict(book, title='已存在的书'), b'different EPUB', {})
        bid, _ = self.stores[0][1].create(book, b'source EPUB', {})
        source = self.root / 'voice.wav'; source.write_bytes(b'RIFF fixture')
        value = self.stores[0][1].load(bid)
        value['chapters'][0]['audio'] = {'path': 'voice.wav', 'url': '/api/books/1/audio/voice.wav', 'status': 'ready'}
        value['chapters'][0]['audio_versions'] = [dict(value['chapters'][0]['audio'])]
        self.stores[0][1].save(value, audio_files={'voice.wav': source})
        result = self.sync[1].import_bundle(self.bundle('book'))
        chapter = self.stores[1][1].load(result['id'])['chapters'][0]
        self.assertEqual(result['id'], 2)
        self.assertEqual(chapter['audio']['url'], '/api/books/2/audio/voice.wav')
        self.assertEqual(chapter['audio_versions'][0]['url'], '/api/books/2/audio/voice.wav')

    def test_import_cleans_active_markup_and_preserves_ruby_and_book_anchors(self):
        self.article(furigana_paragraphs=['<ruby onmouseover="alert(1)">漢字<rt>かんじ</rt></ruby><img src="x" onerror="alert(1)"><script>alert(1)</script>'])
        result = self.sync[1].import_bundle(self.bundle('article'))
        markup = self.stores[1][0].load(result['id'])['furigana_paragraphs'][0]
        self.assertIsNone(BeautifulSoup(markup, 'html.parser').find('script'))
        self.assertNotIn('onmouseover', markup)
        self.assertNotIn('onerror', markup)
        self.assertIn('<rt>かんじ</rt>', markup)
        anchor = 'epub-' + '1' * 20
        html = '<p id="' + anchor + '"><ruby>漢字<rt>かんじ</rt></ruby><img data-book-asset="cover.png" onerror="alert(1)"><a data-book-href="chapter.xhtml#' + anchor + '">次へ</a><script>alert(1)</script></p>'
        book = dict(title='安全な本', original_filename='book.epub', chapters=[dict(id=1, title='章节', source_href='chapter.xhtml', blocks=[dict(id=1, text_ja='漢字', html=html, furigana_html=html)])])
        self.stores[0][1].create(book, b'EPUB markup fixture', {'cover.png': b'cover'})
        result = self.sync[1].import_bundle(self.bundle('book'))
        block = self.stores[1][1].load(result['id'])['chapters'][0]['blocks'][0]
        for field in ('html', 'furigana_html'):
            soup = BeautifulSoup(block[field], 'html.parser')
            self.assertIsNone(soup.find('script'))
            self.assertFalse(any('onerror' in tag.attrs for tag in soup.find_all(True)))
            self.assertEqual(soup.find('ruby').find('rt').text, 'かんじ')
            self.assertEqual(soup.find('p')['id'], anchor)
            self.assertEqual(soup.find('a')['data-book-href'], 'chapter.xhtml#' + anchor)
            self.assertEqual(soup.find('img')['data-book-asset'], 'cover.png')

    def test_rejects_tamper_unlisted_files_and_traversal_without_writing(self):
        from library_sync import LibrarySyncError
        self.article()
        archive = self.bundle('article')
        for filename, replacement in [('files/original.txt', b'tampered'), ('files/../../outside', b'bad'), ('files/.env', b'bad')]:
            with self.subTest(filename=filename):
                out = io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(archive)) as old, zipfile.ZipFile(out, 'w') as new:
                    for name in old.namelist():
                        new.writestr(name, replacement if name == filename else old.read(name))
                    if filename not in old.namelist(): new.writestr(filename, replacement)
                with self.assertRaises(LibrarySyncError): self.sync[1].import_bundle(out.getvalue())
                self.assertEqual(self.stores[1][0].ids(), [])
        with self.assertRaises(LibrarySyncError): self.sync[1].import_bundle(archive, expected_sha256='0' * 64)

    def test_invalid_article_does_not_block_export_of_valid_example(self):
        article = self.article()
        (self.stores[0][0].root / article['_directory'] / 'original.txt').write_text('external change', encoding='utf-8')
        self.stores[0][2].create('有效示例', '日本語。')
        manifest = self.sync[0].manifest()
        self.assertTrue(manifest['errors'])
        item = next(item for item in manifest['items'] if item['title'] == '有效示例')
        result = self.sync[1].import_bundle(self.sync[0].export_bundle(item['key']))
        self.assertEqual(result['status'], 'created')


if __name__ == '__main__':
    unittest.main()
