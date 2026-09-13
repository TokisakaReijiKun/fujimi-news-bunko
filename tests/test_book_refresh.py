import io
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from server import create_app
from test_web import fixture_epub


class BookRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.client = self.app.test_client()

    def tearDown(self):
        import gc
        gc.collect()
        self.temp.cleanup()

    def import_book(self):
        response = self.client.post('/api/books/import', data={'files':(io.BytesIO(fixture_epub()),'test.epub')},content_type='multipart/form-data')
        task_id = response.json['tasks'][0]['id']
        for _ in range(100):
            task = self.client.get('/api/books/tasks/'+task_id).json
            if task['status'] in ('completed','failed'):break
            time.sleep(.02)
        self.assertEqual(task['status'],'completed',task)
        return task['book_id']

    def refresh(self):
        return self.client.post('/api/settings/refresh-storage')

    def test_text_only_epub_has_directory_and_survives_refresh(self):
        bid = self.import_book()
        self.assertTrue(self.app.book_store.folder(bid).is_dir())
        result = self.refresh().json
        self.assertEqual(result['books_scanned'],1)
        self.assertEqual(result['books_removed'],0)
        self.assertIn(bid,self.app.book_store.ids())

    def test_deleted_directory_removes_record_with_restorable_backup(self):
        bid = self.import_book()
        self.client.put(f'/api/books/{bid}/progress',json={'chapter_id':2,'block_index':0})
        self.client.post(f'/api/books/{bid}/chapters/1/bookmarks',json={'block_index':0,'excerpt':'test'})
        shutil.rmtree(self.app.book_store.folder(bid))
        result = self.refresh().json
        self.assertEqual(result['removed_book_ids'],[bid])
        self.assertEqual(result['books_removed'],1)
        self.assertEqual(self.client.get('/api/books').json['books'],[])
        self.assertEqual(self.client.get(f'/api/books/{bid}').status_code,404)
        saved = json.loads((self.root/result['book_records_backup']).read_text(encoding='utf-8'))['books'][0]
        self.assertEqual(saved['id'],bid)
        self.assertTrue(saved['title'])
        self.assertTrue(saved['digest'])
        self.assertEqual(self.refresh().json['books_removed'],0)
        replacement = self.import_book()  # Same EPUB is no longer blocked as duplicate.
        self.assertTrue(self.app.book_store.folder(replacement).is_dir())
        self.assertEqual(len(self.client.get('/api/books').json['books']),1)

    def test_inaccessible_or_non_directory_path_keeps_record(self):
        bid = self.import_book()
        directory = self.app.book_store.folder(bid)
        original_stat = Path.stat
        def stat(path,*args,**kwargs):
            if path==directory:raise PermissionError('test')
            return original_stat(path,*args,**kwargs)
        with patch.object(Path,'stat',stat):
            result=self.refresh().json
        self.assertEqual(result['books_removed'],0)
        self.assertEqual(len(result['invalid_book_records']),1)
        shutil.rmtree(directory);directory.write_text('not a folder',encoding='utf-8')
        result=self.refresh().json
        self.assertEqual(result['books_removed'],0)
        self.assertIn(bid,self.app.book_store.ids())

    def test_backup_failure_does_not_delete_record(self):
        bid=self.import_book();shutil.rmtree(self.app.book_store.folder(bid))
        with patch('book_store.write_json',side_effect=OSError('backup failed')):
            self.assertEqual(self.refresh().status_code,500)
        self.assertIn(bid,self.app.book_store.ids())
