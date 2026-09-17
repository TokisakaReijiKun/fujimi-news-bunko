from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from article_store import ArticleStore, StorageError, db_connection, digest, write_json
from storage_migration import preview, migrate, rollback, flatten_databases


def sample(title='記事の見出し', url='https://example.com/a'):
    return {'title':title,'url':url,'source_name':'Test','created_at':'2026-09-07T23:00:00+08:00',
            'published_at':'2026-09-07','status':'ready','paragraphs':['最初の段落。','次の段落。'],
            'translated_paragraphs':['第一段。',''], 'furigana_paragraphs':['最初の段落。','次の段落。'],
            'original_text':'最初の段落。\n\n次の段落。','full_translation':'','image_paths':[],'video_urls':[]}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.data=Path(self.temp.name)
        self.store=ArticleStore(self.data)

    def tearDown(self):
        self.temp.cleanup()

    def test_files_authority_roundtrip_and_date_memberships(self):
        a=self.store.create(sample(),'2026-09-08')
        self.assertTrue(a['_directory'].startswith('2026-09-07/'))
        folder=self.store.root/a['_directory']
        self.assertTrue((folder/'audio').is_dir());self.assertTrue((folder/'media').is_dir())
        self.assertEqual((folder/'original.txt').read_text(encoding='utf-8'),sample()['original_text'])
        m=json.loads((folder/'article.json').read_text(encoding='utf-8'))
        self.assertNotIn('paragraphs',m['article']);self.assertNotIn('full_translation',m['article'])
        self.assertEqual(a['translated_paragraphs'],['第一段。',''])
        old_path=a['_directory'];a['title']='新しいタイトル';self.store.save(a)
        again=self.store.create(sample(),'2026-09-09')
        self.assertEqual(again['id'],a['id']);self.assertEqual(again['_directory'],old_path)
        self.assertEqual(self.store.days(),['2026-09-09','2026-09-08'])
        self.assertEqual(len(self.store.ids()),1)

    def test_names_conflicts_and_manual_change_detection(self):
        a=self.store.create(sample('CON.','https://example.com/1'),'2026-09-07')
        b=self.store.create(sample('CON.','https://example.com/2'),'2026-09-07')
        c=self.store.create(sample('非法<>:"/\\|?*'+('文'*180),'https://example.com/3'),'2026-09-07')
        self.assertNotEqual(a['_directory'],b['_directory'])
        self.assertTrue(Path(a['_directory']).name.startswith('_CON'))
        self.assertLess(len(Path(c['_directory']).name),66)
        folder=self.store.root/a['_directory']
        (folder/'translation.txt').write_text('不匹配的人工修改',encoding='utf-8')
        with self.assertRaises(StorageError):self.store.load(a['id'])
        report=self.store.rebuild();self.assertEqual(len(report['errors']),1)
        self.assertEqual(report['indexed'],0)

    def test_rebuild_keeps_settings_and_books_and_flags_duplicate_ids(self):
        a=self.store.create(sample(),'2026-09-07')
        self.store.patch(a['id'],{'bookmarked':True})
        with db_connection(self.store.db_path) as db:
            db.executescript("CREATE TABLE settings(key TEXT,value TEXT); INSERT INTO settings VALUES('x','y'); CREATE TABLE books(id INTEGER,payload TEXT); INSERT INTO books VALUES(8,'unchanged'); DELETE FROM articles;DELETE FROM article_days;")
        self.assertEqual(self.store.rebuild()['indexed'],1)
        self.assertEqual(self.store.ids(bookmarked=True),[a['id']])
        with db_connection(self.store.db_path) as db:
            self.assertEqual(db.execute('SELECT value FROM settings').fetchone()[0],'y')
            self.assertEqual(db.execute('SELECT payload FROM books').fetchone()[0],'unchanged')
            self.assertNotIn('payload',[r['name'] for r in db.execute('PRAGMA table_info(articles)')])
        duplicate=self.store.root/'2026-09-07/copy'
        shutil.copytree(self.store.root/a['_directory'],duplicate)
        self.assertTrue(self.store.rebuild()['errors'])

    def test_interrupted_switch_recovers_previous_or_new_version(self):
        a=self.store.create(sample(),'2026-09-07')
        original=os.replace
        def interrupt(source,target):
            if Path(source).name=='new':raise KeyboardInterrupt()
            return original(source,target)
        a['title']='new title'
        with patch('article_store.os.replace',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):self.store.save(a)
        restored=ArticleStore(self.data)
        self.assertEqual(restored.load(a['id'])['title'],sample()['title'])
        a=restored.load(a['id']);a['title']='committed title'
        with patch.object(restored,'_index',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):restored.save(a)
        recovered=ArticleStore(self.data)
        self.assertEqual(recovered.load(a['id'])['title'],'committed title')

    def test_save_retries_temporary_windows_directory_sharing_violation(self):
        article=self.store.create(sample(),'2026-09-07')
        article['title']='Windows retry'
        original=os.replace
        replacements=[]
        def briefly_locked(source,target):
            source,target=Path(source),Path(target)
            if target.name=='old':
                replacements.append((source,target))
                if len(replacements)==1:
                    raise PermissionError(5,'simulated Windows directory sharing violation')
            return original(source,target)
        with patch('article_store.os.replace',side_effect=briefly_locked):
            saved=self.store.save(article)
        self.assertEqual(saved['title'],'Windows retry')
        self.assertEqual(len(replacements),2)
        self.assertEqual(self.store.load(article['id'])['title'],'Windows retry')

    def test_asset_isolation_missing_asset_and_stale_updates(self):
        a=self.store.create(sample(),'2026-09-07')
        source=self.data/'fixture.jpg';source.write_bytes(b'fixture')
        a['_assets']=[{'path':'media/image-001.jpg','kind':'image','legacy_names':['old.jpg']}]
        a['image_paths']=['media/image-001.jpg']
        a=self.store.save(a,files={'media/image-001.jpg':source})
        self.assertEqual(self.store.asset(a['id'],'media/image-001.jpg').read_bytes(),b'fixture')
        for name in ('../../.env','article.json','media/../original.txt'):
            with self.assertRaises((LookupError,StorageError)):self.store.asset(a['id'],name)
        self.store.patch(a['id'],{'bookmarked':True})
        with self.assertRaises(StorageError):self.store.save(a)
        self.store.asset(a['id'],'media/image-001.jpg').unlink()
        self.assertTrue(self.store.rebuild()['errors'])

    def test_tts_manifest_commit_survives_index_interruption_without_runtime_folder(self):
        a=self.store.create(sample(),'2026-09-07')
        source=self.data/'audio.wav';source.write_bytes(b'synthetic audio')
        a['_assets']=[{'path':'audio/voice.wav','kind':'audio'}]
        a['audio_path']='audio/voice.wav'
        with patch.object(self.store,'_index',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.store.save_tts(a,files={'audio/voice.wav':source})
        self.assertFalse((self.data/'tts').exists())
        restored=ArticleStore(self.data)
        self.assertEqual(restored.asset(a['id'],'audio/voice.wav').read_bytes(),b'synthetic audio')
        self.assertEqual(restored.load(a['id'])['paragraphs'],a['paragraphs'])

    def test_tts_commit_never_renames_article_directory(self):
        a=self.store.create(sample(),'2026-09-07')
        folder=self.store.root/a['_directory']
        source=self.data/'audio.wav';source.write_bytes(b'synthetic audio')
        a['_assets']=[{'path':'audio/voice.wav','kind':'audio'}]
        a['audio_path']='audio/voice.wav'
        original=os.replace
        calls=[]
        def no_directory_replace(source_path,target_path):
            source_path,target_path=Path(source_path),Path(target_path)
            calls.append((source_path,target_path))
            if source_path==folder or target_path.name=='old':
                raise PermissionError(5,'simulated Windows directory sharing violation')
            return original(source_path,target_path)
        with patch('article_store.os.replace',side_effect=no_directory_replace):
            saved=self.store.save_tts(a,files={'audio/voice.wav':source})
        self.assertEqual(saved['audio_path'],'audio/voice.wav')
        self.assertEqual(self.store.asset(a['id'],'audio/voice.wav').read_bytes(),b'synthetic audio')
        self.assertFalse(any(source==folder or target.name=='old' for source,target in calls))

    def test_index_failure_keeps_committed_file_and_recovers_index(self):
        a=self.store.create(sample(),'2026-09-07');a['title']='Committed despite index failure'
        original=self.store._index
        calls=[]
        def once(*args):
            calls.append(1)
            if len(calls)==1:raise sqlite3.OperationalError('database is locked')
            return original(*args)
        with patch.object(self.store,'_index',side_effect=once):
            with self.assertRaises(sqlite3.OperationalError):self.store.save(a)
        self.assertEqual(self.store.load(a['id'])['title'],'Committed despite index failure')
        with db_connection(self.store.db_path) as db:
            self.assertEqual(db.execute('SELECT title FROM articles').fetchone()[0],'Committed despite index failure')

    def test_each_article_has_own_copy_and_audio_registration(self):
        first=self.store.create(sample(),'2026-09-07')
        second=self.store.create(sample(url='https://example.com/b'),'2026-09-07')
        source=self.data/'fixture.jpg';source.write_bytes(b'same image')
        for a in (first,second):
            a['_assets']=[{'path':'media/image-001.jpg','kind':'image'}, {'path':'audio/test-parameters/001.mp3','kind':'audio'}]
            a.update(image_paths=['media/image-001.jpg'],audio_path='audio/test-parameters/001.mp3')
            self.store.save(a,files={'media/image-001.jpg':source,'audio/test-parameters/001.mp3':source})
        p=self.store.asset(first['id'],'media/image-001.jpg')
        q=self.store.asset(second['id'],'media/image-001.jpg')
        self.assertNotEqual(p,q);p.write_bytes(b'changed')
        self.assertEqual(q.read_bytes(),b'same image')
        self.assertTrue(self.store.wire(self.store.load(second['id']))['audio_path'].startswith('/api/articles/'))


class MigrationTests(unittest.TestCase):
    def test_flatten_database_folder_preserves_data_and_preview_is_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            store=ArticleStore(data)
            a=store.create(sample(),'2026-09-07')
            before=(store.root/a['_directory']/'article.json').read_bytes()
            nested=data/'databases';nested.mkdir()
            os.replace(data/'fujimi.sqlite3',nested/'fujimi.sqlite3')
            with db_connection(nested/'dictionary-search.sqlite3') as db:
                db.execute('CREATE TABLE words(value TEXT)')
                db.execute("INSERT INTO words VALUES('preserved')")
            files=sorted(p.relative_to(data).as_posix() for p in data.rglob('*'))
            self.assertEqual(preview(data)['status'],'flatten_databases')
            self.assertEqual(files,sorted(p.relative_to(data).as_posix() for p in data.rglob('*')))
            with self.assertRaises(ValueError): ArticleStore(data)
            result=migrate(data)
            self.assertEqual(result['status'],'flattened')
            self.assertFalse(nested.exists())
            restored=ArticleStore(data)
            self.assertEqual(restored.load(a['id'])['paragraphs'],a['paragraphs'])
            self.assertEqual(before,(store.root/a['_directory']/'article.json').read_bytes())
            with db_connection(data/'dictionary-search.sqlite3') as db:
                self.assertEqual(db.execute('SELECT value FROM words').fetchone()[0],'preserved')
            self.assertEqual(preview(data)['status'],'already_migrated')

    def test_flatten_conflict_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);ArticleStore(data)
            (data/'databases').mkdir()
            shutil.copy2(data/'fujimi.sqlite3',data/'databases/fujimi.sqlite3')
            self.assertTrue(flatten_databases(data)['errors'])
            with self.assertRaises(StorageError):flatten_databases(data,apply=True)
            self.assertTrue((data/'databases/fujimi.sqlite3').exists())

    def build_legacy(self,data,missing=False):
        (data/'media').mkdir()
        if not missing:(data/'media/old.jpg').write_bytes(b'old bytes')
        with db_connection(data/'fujimi.sqlite3') as db:
            db.executescript('CREATE TABLE articles(id INTEGER PRIMARY KEY,url TEXT,day TEXT,bookmarked INTEGER,payload TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE books(id INTEGER PRIMARY KEY,payload TEXT);')
            a=sample();a['image_paths']=['old.jpg'];a['image_captions']=['図注'];a['image_positions']=[-1]
            db.execute('INSERT INTO articles VALUES(7,?,?,?,?)',(a['url'],'2026-09-08',1,json.dumps(a,ensure_ascii=False)))
            db.execute("INSERT INTO settings VALUES('test','preserved')")
            db.execute("INSERT INTO books VALUES(1,'book-payload')")
        (data/'inspection').mkdir();(data/'inspection/a.html').write_text('debug',encoding='utf-8')
        (data/'before-example.sqlite3').write_bytes(b'backup')
        (data/'unknown.bin').write_bytes(b'unknown')

    def test_preview_migrate_repeat_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);self.build_legacy(data)
            before=sorted(str(p.relative_to(data)) for p in data.rglob('*'))
            p=preview(data)
            self.assertEqual(before,sorted(str(p.relative_to(data)) for p in data.rglob('*')))
            self.assertEqual(p['unknown_files'],['unknown.bin'])
            result=migrate(data);self.assertEqual(result['phase'],'complete')
            store=ArticleStore(data);a=store.load(7)
            self.assertTrue(a['bookmarked']);self.assertEqual(a['paragraphs'],sample()['paragraphs'])
            self.assertEqual(a['edition_dates'],['2026-09-08'])
            self.assertEqual(store.legacy_asset('old.jpg').read_bytes(),b'old bytes')
            self.assertEqual(a['image_captions'],['図注'])
            self.assertFalse((data/'media').exists());self.assertTrue((data/'fujimi.sqlite3').exists())
            self.assertTrue((data/'diagnostics/inspection/a.html').exists())
            self.assertEqual(migrate(data)['phase'],'complete')
            store.patch(7,{'title':'post migration change'})
            restored=rollback(data)
            self.assertTrue((data/restored['preserved_new_data']/'articles').exists())
            with db_connection(data/'fujimi.sqlite3') as db:
                self.assertEqual(json.loads(db.execute('SELECT payload FROM articles').fetchone()[0])['title'],sample()['title'])
            self.assertTrue((data/'media/old.jpg').exists())

    def test_missing_media_refuses_to_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);self.build_legacy(data,missing=True)
            self.assertTrue(preview(data)['errors'])
            with self.assertRaises(StorageError):migrate(data)
            self.assertFalse((data/'databases/fujimi.sqlite3').exists())

    def test_interrupted_migration_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);self.build_legacy(data)
            original=os.replace
            def interrupt(source,target):
                if Path(target)==data/'articles':raise KeyboardInterrupt()
                return original(source,target)
            with patch('storage_migration.os.replace',side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):migrate(data)
            self.assertEqual(migrate(data)['phase'],'complete')
            self.assertEqual(ArticleStore(data).load(7)['paragraphs'],sample()['paragraphs'])
