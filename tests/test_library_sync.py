"""Real file-store transfers; all libraries live in temporary directories."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from bs4 import BeautifulSoup

from article_store import ArticleStore, digest
from book_store import BookStore
from example_store import ExampleStore


class ExistingFileBytes(bytes):
    """Mark disk reads so tests can distinguish them from newly generated data."""


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

    def test_manifest_compares_path_size_without_reading_content(self):
        article = self.article()
        self.stores[0][1].create(dict(title='本', chapters=[dict(id=1, title='章', blocks=[dict(text_ja='本文')])]), b'EPUB fixture', {'cover.png': b'cover'})
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('清单不得读取文件正文')):
            manifest = self.sync[0].manifest()
        self.assertFalse(manifest['errors'], manifest)
        self.assertEqual(manifest['file_comparison'], 'path-size-v1')
        item = next(item for item in manifest['items'] if item['kind'] == 'article')
        self.assertEqual(item['files']['original.txt'], len('日本語の本文。'.encode()))
        self.assertFalse(item['bookmarked'])
        self.assertNotIn('fingerprint', item)

    def test_delta_bundle_only_includes_new_attachment_and_metadata(self):
        article = self.article()
        key = next(item['key'] for item in self.sync[0].manifest()['items'] if item['kind'] == 'article')
        self.sync[1].import_bundle(self.sync[0].export_bundle(key))
        known = next(item['files'] for item in self.sync[1].manifest()['items'] if item['key'] == key)
        image = self.root / 'new.jpg'; image.write_bytes(b'new image' * 100000)
        article.update(image_paths=['media/new.jpg'], _assets=[dict(path='media/new.jpg', kind='image')])
        self.stores[0][0].save(article, files={'media/new.jpg': image})
        bundle = self.sync[0].export_bundle(key, known_files=known)
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            record = json.loads(archive.read('bundle.json'))
            self.assertEqual(record['version'], 2)
            self.assertEqual(set(record['included']), {'article.json', 'media/new.jpg'})
            self.assertEqual(set(archive.namelist()), {'bundle.json', 'files/article.json', 'files/media/new.jpg'})
            self.assertTrue(all('sha256' not in spec for spec in record['files']))
            self.assertEqual(archive.getinfo('files/media/new.jpg').compress_type, zipfile.ZIP_STORED)
        self.assertEqual(self.sync[1].import_bundle(bundle)['status'], 'updated')
        self.assertEqual(self.stores[1][0].asset(self.stores[1][0].ids()[0], 'media/new.jpg').read_bytes(), image.read_bytes())

    def test_same_path_and_size_attachment_keeps_local_bytes(self):
        for side, content in [(0, b'AAA'), (1, b'BBB')]:
            article = self.article(side)
            image = self.root / ('photo' + str(side)); image.write_bytes(content)
            article.update(image_paths=['media/photo.png'], _assets=[dict(path='media/photo.png', kind='image')])
            self.stores[side][0].save(article, files={'media/photo.png': image})
        result = self.sync[1].import_bundle(self.bundle('article'))
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(self.stores[1][0].asset(result['id'], 'media/photo.png').read_bytes(), b'BBB')

    def test_delta_bundle_rejects_missing_or_wrong_length_local_file(self):
        from library_sync import LibrarySyncError
        self.article()
        item = next(item for item in self.sync[0].manifest()['items'] if item['kind'] == 'article')
        bundle = self.sync[0].export_bundle(item['key'], known_files=item['files'])
        with self.assertRaises(LibrarySyncError): self.sync[1].import_bundle(bundle)
        local = self.article(1)
        path = self.stores[1][0].root / local['_directory'] / 'original.txt'
        for content in (b'x', b'x' * 100):
            path.write_bytes(content)
            with self.assertRaises(LibrarySyncError): self.sync[1].import_bundle(bundle)

    def test_repeated_delta_export_uses_cached_key_and_never_hashes_files(self):
        self.article()
        item = next(item for item in self.sync[0].manifest()['items'] if item['kind'] == 'article')
        self.sync[1].import_bundle(self.sync[0].export_bundle(item['key']))
        target = next(item for item in self.sync[1].manifest()['items'] if item['kind'] == 'article')
        with patch.object(self.sync[0], '_entities', side_effect=AssertionError('不能逐项重扫文库')), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('不能重读未变化的文件')), \
                patch('article_store.digest', side_effect=AssertionError('同步不校验文件hash')), \
                patch('book_store.digest', side_effect=AssertionError('同步不校验文件hash')), \
                patch('example_store.digest', side_effect=AssertionError('同步不校验文件hash')):
            bundle = self.sync[0].export_bundle(item['key'], known_files=target['files'])
            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                self.assertEqual(set(archive.namelist()), {'bundle.json', 'files/article.json'})

    def test_book_delta_preserves_progress_without_rereading_epub(self):
        book = dict(title='差量书籍', chapters=[dict(id=1, title='章', blocks=[dict(id=1, text_ja='本文。')])])
        bid, _ = self.stores[0][1].create(book, b'EPUB fixture', {})
        key = next(item['key'] for item in self.sync[0].manifest()['items'] if item['kind'] == 'book')
        received = self.sync[1].import_bundle(self.sync[0].export_bundle(key))
        self.stores[1][1].patch_state(received['id'], {'progress': {'offset': 42}})
        known = next(item['files'] for item in self.sync[1].manifest()['items'] if item['key'] == key)
        value = self.stores[0][1].load(bid)
        value['chapters'][0]['blocks'][0]['text_zh'] = '中文正文。'
        self.stores[0][1].save(value, assets={'new.png': b'new image'})
        original_read = Path.read_bytes
        def read(path):
            if path.suffix == '.epub':
                raise AssertionError('书籍补齐不得读取已有EPUB')
            return original_read(path)
        with patch.object(Path, 'read_bytes', read):
            bundle = self.sync[0].export_bundle(key, known_files=known)
            result = self.sync[1].import_bundle(bundle)
        self.assertEqual(result['status'], 'updated')
        saved = self.stores[1][1].load(received['id'])
        self.assertEqual(saved['progress'], {'offset': 42})
        self.assertEqual(saved['chapters'][0]['blocks'][0]['text_zh'], '中文正文。')

    def test_article_delta_commit_does_not_read_existing_large_media(self):
        old = self.root / 'old.jpg'; old.write_bytes(b'old media' * 100000)
        article = self.article()
        article.update(image_paths=['media/old.jpg'], _assets=[dict(path='media/old.jpg', kind='image')])
        article = self.stores[0][0].save(article, files={'media/old.jpg': old})
        key = next(item['key'] for item in self.sync[0].manifest()['items'] if item['kind'] == 'article')
        local = self.sync[1].import_bundle(self.sync[0].export_bundle(key))
        known = next(item['files'] for item in self.sync[1].manifest()['items'] if item['key'] == key)
        new = self.root / 'new.jpg'; new.write_bytes(b'new media')
        article['image_paths'].append('media/new.jpg')
        article['_assets'].append(dict(path='media/new.jpg', kind='image'))
        self.stores[0][0].save(article, files={'media/new.jpg': new})
        self.stores[0][0].set_bookmarked(article['id'], True)
        read_bytes = Path.read_bytes
        def read(path):
            if path.name == 'old.jpg':
                raise AssertionError('实际提交新附件时不得重读旧媒体')
            return read_bytes(path)
        with patch.object(Path, 'read_bytes', read):
            result = self.sync[1].import_bundle(self.sync[0].export_bundle(key, known_files=known))
        self.assertEqual(result['status'], 'updated')
        saved = self.stores[1][0].load(local['id'])
        self.assertTrue(saved['bookmarked'])
        self.assertEqual(self.stores[1][0].asset(saved['id'], 'media/new.jpg').read_bytes(), b'new media')
        self.assertEqual(self.stores[1][0].asset(saved['id'], 'media/old.jpg').read_bytes(), old.read_bytes())

    def test_book_delta_commit_never_hashes_old_chapter_bytes(self):
        book = dict(title='附件书籍', chapters=[dict(id=1, title='章', blocks=[dict(id=1, text_ja='本文。')])])
        bid, _ = self.stores[0][1].create(book, b'EPUB fixture', {'old.jpg': b'old media' * 100000})
        key = next(item['key'] for item in self.sync[0].manifest()['items'] if item['kind'] == 'book')
        local = self.sync[1].import_bundle(self.sync[0].export_bundle(key))
        known = next(item['files'] for item in self.sync[1].manifest()['items'] if item['key'] == key)
        self.stores[0][1].save(self.stores[0][1].load(bid), assets={'new.jpg': b'new media'})
        read_bytes = Path.read_bytes
        def read(path):
            if path.name == 'old.jpg' or path.suffix == '.epub':
                raise AssertionError('实际提交新附件时不得重读旧附件或EPUB')
            blob = read_bytes(path)
            return ExistingFileBytes(blob) if path.parent.name == 'chapters' else blob
        def hash_new(blob):
            if isinstance(blob, ExistingFileBytes):
                raise AssertionError('实际提交不得对旧章节做hash比较')
            return digest(blob)
        with patch.object(Path, 'read_bytes', read), patch('book_store.digest', hash_new):
            result = self.sync[1].import_bundle(self.sync[0].export_bundle(key, known_files=known))
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(self.stores[1][1].asset(local['id'], 'new.jpg').read_bytes(), b'new media')

    def test_example_delta_commit_does_not_hash_existing_text_or_read_old_audio(self):
        example = self.stores[0][2].create('差量示例', '日本語。')
        old = self.root / 'old.wav'; old.write_bytes(b'old audio' * 100000)
        example = self.stores[0][2].save_audio(example['id'], None, old, dict(voice_name='旧声线', text_sha256=digest('日本語。'.encode())))
        old_name = Path(example['audio_versions'][0]['path']).name
        key = next(item['key'] for item in self.sync[0].manifest()['items'] if item['title'] == '差量示例')
        local = self.sync[1].import_bundle(self.sync[0].export_bundle(key))
        known = next(item['files'] for item in self.sync[1].manifest()['items'] if item['key'] == key)
        new = self.root / 'new.wav'; new.write_bytes(b'new audio')
        self.stores[0][2].save_audio(example['id'], None, new, dict(voice_name='新声线', text_sha256=digest('日本語。'.encode())))
        read_bytes = Path.read_bytes
        def read(path):
            if path.name == old_name:
                raise AssertionError('实际提交新音频时不得重读旧音频')
            blob = read_bytes(path)
            return ExistingFileBytes(blob) if path.name in ('original.txt', 'translation.txt') else blob
        def hash_new(blob):
            if isinstance(blob, ExistingFileBytes):
                raise AssertionError('实际提交不得对旧示例文本做hash比较')
            return digest(blob)
        with patch.object(Path, 'read_bytes', read), patch('example_store.digest', hash_new):
            result = self.sync[1].import_bundle(self.sync[0].export_bundle(key, known_files=known))
        self.assertEqual(result['status'], 'updated')
        saved = self.stores[1][2].get(local['id'])
        self.assertEqual(len(saved['audio_versions']), 2)

    def test_book_manifest_describes_chapter_enhancements_without_content_hashes(self):
        book = dict(title='增强标记', chapters=[
            dict(id=1, title='一', blocks=[dict(id=1, text_ja='本文。', text_zh='译文。'), dict(id=2, text_ja='漢字', furigana_html='<ruby>漢字<rt>かんじ</rt></ruby>')]),
            dict(id=2, title='二', blocks=[dict(id=1, text_ja='次。')])])
        bid, _ = self.stores[0][1].create(book, b'EPUB fixture', {})
        audio = self.root / 'voice.wav'; audio.write_bytes(b'audio fixture')
        value = self.stores[0][1].load(bid)
        chapter = value['chapters'][0]
        chapter['audio'] = {'path': 'voice.wav'}
        chapter['audio_versions'] = [{'path': 'voice.wav'}]
        self.stores[0][1].save(value, audio_files={'voice.wav': audio})
        item = next(item for item in self.sync[0].manifest()['items'] if item['kind'] == 'book')
        self.assertEqual(item['chapter_features'], {'chapters/0001.json': ['audio:voice.wav', 'ruby:1', 'zh:0'], 'chapters/0002.json': []})

    def test_book_delta_appends_missing_voice_versions_and_preserves_existing_voice(self):
        voice_a = dict(path='A.wav', voice_name='A')
        book = dict(title='双声线书籍', chapters=[dict(id=1, title='章', audio=voice_a,
            audio_versions=[voice_a], blocks=[dict(id=1, text_ja='本文。', audio=voice_a, audio_versions=[voice_a])])])
        audio = self.root / 'voice.wav'; audio.write_bytes(b'audio fixture')
        bid, _ = self.stores[0][1].create(book, b'EPUB fixture', {}, audio_files={'A.wav': audio})
        key = next(item['key'] for item in self.sync[0].manifest()['items'] if item['kind'] == 'book')
        local = self.sync[1].import_bundle(self.sync[0].export_bundle(key))
        known = next(item['files'] for item in self.sync[1].manifest()['items'] if item['key'] == key)
        value = self.stores[0][1].load(bid)
        voice_b = dict(path='B.wav', voice_name='B')
        value['chapters'][0]['audio_versions'].append(voice_b)
        value['chapters'][0]['blocks'][0]['audio_versions'].append(voice_b)
        self.stores[0][1].save(value, audio_files={'B.wav': audio})
        bundle = self.sync[0].export_bundle(key, known_files=known)
        self.assertEqual(self.sync[1].import_bundle(bundle)['status'], 'updated')
        chapter = self.stores[1][1].load(local['id'])['chapters'][0]
        self.assertEqual([audio['path'] for audio in chapter['audio_versions']], ['A.wav', 'B.wav'])
        self.assertEqual([audio['path'] for audio in chapter['blocks'][0]['audio_versions']], ['A.wav', 'B.wav'])
        self.assertEqual(chapter['audio']['path'], 'A.wav')
        item = next(item for item in self.sync[1].manifest()['items'] if item['key'] == key)
        self.assertEqual(item['chapter_features']['chapters/0001.json'], ['audio:A.wav', 'audio:B.wav'])
        self.assertEqual(self.sync[1].import_bundle(bundle)['status'], 'unchanged')

    def test_invalid_article_does_not_block_export_of_valid_example(self):
        article = self.article()
        (self.stores[0][0].root / article['_directory'] / 'original.txt').unlink()
        self.stores[0][2].create('有效示例', '日本語。')
        manifest = self.sync[0].manifest()
        self.assertTrue(manifest['errors'])
        item = next(item for item in manifest['items'] if item['title'] == '有效示例')
        result = self.sync[1].import_bundle(self.sync[0].export_bundle(item['key']))
        self.assertEqual(result['status'], 'created')

    def test_new_article_import_does_not_read_unrelated_existing_text(self):
        old = self.article(1, url='https://example.test/existing')
        self.article(0, url='https://example.test/new')
        bundle = self.bundle('article')
        folder = self.stores[1][0].root / old['_directory']
        forbidden = {(folder / name).resolve() for name in ('original.txt', 'translation.txt', 'furigana.html')}
        original = Path.read_bytes
        def guarded(path):
            self.assertNotIn(path.resolve(), forbidden, 'New sync imports must not scan unrelated article bodies')
            return original(path)
        with patch.object(Path, 'read_bytes', guarded):
            self.assertEqual(self.sync[1].import_bundle(bundle)['status'], 'created')


if __name__ == '__main__':
    unittest.main()
