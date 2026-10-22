"""Book folders are authoritative; SQLite stores only shelf metadata."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

from article_store import ArticleStore, db_connection, directory_name, safe_path, write_json, StorageError, digest


def source_epub_name(value):
    """Keep the uploaded EPUB name without accepting an embedded path."""
    name=re.split(r'[/\\]',str(value or ''))[-1].strip()
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).rstrip(' .')
    if not name.lower().endswith('.epub'):name=(name or 'source')+'.epub'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)',name,re.I):name='_'+name
    if len(name)>120:name=name[:115].rstrip(' .')+'.epub'
    return name


class BookStore:
    def __init__(self, data):
        self.data=Path(data).resolve();self.root=self.data/'books';self.db=self.data/'fujimi.sqlite3'
        self.locks=ArticleStore(self.data);self.root.mkdir(exist_ok=True)
        self.transactions=self.data/'diagnostics/book-transactions';self.transactions.mkdir(parents=True,exist_ok=True)
        with self.locks.locked():
            self.recover()
            with db_connection(self.db) as db:
                columns={r['name'] for r in db.execute('PRAGMA table_info(books)')}
                if 'payload' in columns:raise StorageError('旧书架尚未迁移，请执行 scripts/migrate_books.py。')
                db.executescript('''CREATE TABLE IF NOT EXISTS books(id INTEGER PRIMARY KEY,digest TEXT UNIQUE,directory TEXT UNIQUE,title TEXT,author TEXT,series TEXT,volume TEXT,imported_at TEXT,last_read_at TEXT);
                    CREATE TABLE IF NOT EXISTS book_sequence(id INTEGER PRIMARY KEY,next_id INTEGER NOT NULL);
                    INSERT OR IGNORE INTO book_sequence VALUES(1,1);''')

    def recover(self):
        for path in self.transactions.glob('*/journal.json'):
            job=json.loads(path.read_text(encoding='utf-8'));target=safe_path(self.root,job['directory'])
            target.mkdir(parents=True,exist_ok=True)
            for filename in job['files']:
                source=safe_path(path.parent/'new',filename);dest=safe_path(target,filename)
                if source.exists():dest.parent.mkdir(parents=True,exist_ok=True);os.replace(source,dest)
            with db_connection(self.db) as db:
                cols={r['name'] for r in db.execute('PRAGMA table_info(books)')}
            if 'directory' in cols:self._index(target)
            shutil.rmtree(path.parent)

    def _index(self, folder):
        meta=json.loads((folder/'book.json').read_text(encoding='utf-8'))
        state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
        b=meta['book'];bid=b['id']
        with db_connection(self.db) as db:
            db.execute('''INSERT INTO books VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET digest=excluded.digest,directory=excluded.directory,title=excluded.title,author=excluded.author,series=excluded.series,volume=excluded.volume,imported_at=excluded.imported_at,last_read_at=excluded.last_read_at''',
                       (bid,meta['digest'],folder.name,b['title'],b.get('author',''),b.get('series',''),b.get('volume',''),b.get('imported_at',''),state.get('last_read_at','')))
            db.execute('UPDATE book_sequence SET next_id=MAX(next_id,?) WHERE id=1',(bid+1,))

    def folder(self,bid):
        with db_connection(self.db) as db:row=db.execute('SELECT directory FROM books WHERE id=?',(bid,)).fetchone()
        if not row:raise LookupError('书籍不存在。')
        return safe_path(self.root,row['directory'])

    def load(self,bid,full=True):
        with self.locks.locked():
            self.recover();folder=self.folder(bid)
            try:
                meta=json.loads((folder/'book.json').read_text(encoding='utf-8'));state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
                if meta['version']!=2:raise StorageError('不支持的书籍存储版本。')
                source_file=meta.get('source_file','source.epub')
                if meta.get('source_sha256'):
                    source=safe_path(folder,source_file)
                    if not source.is_file() or digest(source.read_bytes())!=meta['source_sha256']:
                        raise StorageError('原始 EPUB 缺失或校验失败。')
                b=deepcopy(meta['book']);b.update(state);b['_revision']=state.get('revision',1)
                if isinstance(b.get('bookmarks'), list):
                    b['bookmarks'] = b['bookmarks'][:1]
                if full:
                    for ch in b['chapters']:
                        blob=safe_path(folder,ch['file']).read_bytes()
                        if digest(blob)!=ch['sha256']:raise StorageError('章节校验失败：'+ch['title'])
                        ch.update(json.loads(blob))
                b['cover_url']=f"/api/books/{bid}/assets/{b['cover_path']}" if b.get('cover_path') else ''
                return b
            except FileNotFoundError as e:raise LookupError('书籍目录或章节文件已被删除，请刷新书架。') from e

    def chapter(self,bid,cid):
        with self.locks.locked():
            b=self.load(bid,False)
            ch=next((c for c in b['chapters'] if c['id']==cid),None)
            if not ch:raise LookupError('章节不存在。')
            blob=safe_path(self.folder(bid),ch['file']).read_bytes()
            if digest(blob)!=ch['sha256']:raise StorageError('章节文件校验失败。')
            return b,json.loads(blob)

    def save(self,b, directory=None, assets=None, original=None, digest_value=None, audio_files=None, audio_remove=None, *, tts=False):
        with self.locks.locked():
            self.recover();bid=b['id']
            folder=safe_path(self.root,directory) if directory else self.folder(bid)
            oldmeta=json.loads((folder/'book.json').read_text(encoding='utf-8')) if (folder/'book.json').exists() else None
            state_path=folder/'state.json';oldstate=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
            if oldmeta and b.get('_revision')!=oldstate.get('revision',1):raise StorageError('书籍已被其他操作更新，请重新打开。')
            book={k:deepcopy(v) for k,v in b.items() if k not in ('progress','bookmarks','last_read_at','cover_url') and not k.startswith('_')}
            book['title']=book['title'].strip();book['author']=book.get('author','').strip()
            state={k:deepcopy(b.get(k,{} if k=='progress' else [] if k=='bookmarks' else '')) for k in ('progress','bookmarks','last_read_at')}
            if isinstance(state.get('bookmarks'), list):
                state['bookmarks'] = state['bookmarks'][:1]
            state['revision']=oldstate.get('revision',0)+1
            files={};summary=[]
            for ch in book['chapters']:
                # A transferred book can receive a different local ID. Playback URLs
                # are derived from the local record and never trusted from its source.
                for audio in [ch.get('audio'), *ch.get('audio_versions', [])]:
                    if isinstance(audio, dict) and audio.get('path'):
                        safe_path(folder/'audio',audio['path'])
                        audio['url']=f"/api/books/{bid}/audio/{audio['path']}"
                name=f"chapters/{ch['id']:04d}.json"
                content={k:v for k,v in ch.items() if k not in ('file','sha256')}
                blob=json.dumps(content,ensure_ascii=False,indent=2).encode('utf-8')
                summary.append({k:v for k,v in content.items() if k!='blocks'} | {'file':name,'sha256':digest(blob)})
                dest=folder/name
                if not dest.exists() or digest(dest.read_bytes())!=digest(blob):files[name]=blob
            book['chapters']=summary
            resources=deepcopy(oldmeta.get('resources',{})) if oldmeta else {}
            audio_manifest=deepcopy(oldmeta.get('audio',{})) if oldmeta else {}
            for path in (audio_remove or ()):
                audio_manifest.pop(path, None)
            for path, source in (audio_files or {}).items():
                safe_path(folder/'audio',path)
                blob=Path(source).read_bytes()
                files['audio/'+path]=blob
                audio_manifest[path]={'sha256':digest(blob),'bytes':len(blob)}
            for path,blob in (assets or {}).items():
                safe_path(folder/'resources',path)
                files['resources/'+path]=blob;resources[path]={'sha256':digest(blob),'bytes':len(blob)}
            if original is not None:
                source_name=source_epub_name(book.get('original_filename') or (oldmeta or {}).get('source_file'))
                files[source_name]=original
                source_sha=digest(original)
            else:
                source_name=(oldmeta or {}).get('source_file','source.epub')
                source_sha=oldmeta.get('source_sha256') if oldmeta else None
            meta={'version':2,'digest':digest_value or (oldmeta['digest'] if oldmeta else b.get('digest','')),
                  'source_file':source_name,'source_sha256':source_sha,'book':book,'resources':resources,'audio':audio_manifest}
            files['book.json']=json.dumps(meta,ensure_ascii=False,indent=2).encode('utf-8')
            files['state.json']=json.dumps(state,ensure_ascii=False,indent=2).encode('utf-8')
            job=self.transactions/uuid.uuid4().hex;stage=job/'new';stage.mkdir(parents=True)
            for path,blob in files.items():
                destination=safe_path(stage,path);destination.parent.mkdir(parents=True,exist_ok=True)
                with destination.open('wb') as f:f.write(blob);f.flush();os.fsync(f.fileno())
            write_json(job/'journal.json',{'directory':folder.name,'files':list(files)})
            self.recover()
            for name in ('resources','audio'): (folder/name).mkdir(exist_ok=True)
            return self.load(bid)

    def create(self,b,blob,assets,audio_files=None):
        with self.locks.locked():
            sha=digest(blob)
            with db_connection(self.db) as db:
                row=db.execute('SELECT id FROM books WHERE digest=?',(sha,)).fetchone()
                if row:
                    if (self.folder(row['id'])/'book.json').exists():return row['id'],True
                    raise StorageError('同一书籍记录的目录已不存在，请先刷新书架。')
                bid=db.execute('SELECT next_id FROM book_sequence WHERE id=1').fetchone()[0]
                db.execute('UPDATE book_sequence SET next_id=next_id+1 WHERE id=1')
            name=directory_name(b['title'],bid,55)
            if (self.root/name).exists():name=name[:45]+'--'+str(bid)
            self.save(dict(b,id=bid),directory=name,assets=assets,original=blob,digest_value=sha,audio_files=audio_files)
            return bid,False

    def ids(self):
        with db_connection(self.db) as db:return [r[0] for r in db.execute('SELECT id FROM books')]

    def asset(self,bid,path):
        folder=self.folder(bid);meta=json.loads((folder/'book.json').read_text(encoding='utf-8'))
        if path not in meta['resources']:raise LookupError('书籍资源不存在。')
        target=safe_path(folder/'resources',path)
        if not target.is_file():raise LookupError('书籍资源文件不存在。')
        return target

    def patch_state(self,bid,changes):
        with self.locks.locked():
            self.recover()
            folder=self.folder(bid);state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
            for k,v in changes.items():
                if k=='progress':state.setdefault(k,{}).update(v)
                elif k=='bookmarks':state[k]=list(v or [])[:1]
                else:state[k]=v
            state['revision']=state.get('revision',0)+1
            write_json(folder/'state.json',state);self._index(folder)
            return self.load(bid,False)

    def audio_asset(self,bid,path):
        with self.locks.locked():
            folder=self.folder(bid)
            meta=json.loads((folder/'book.json').read_text(encoding='utf-8'))
            entry=meta.get('audio',{}).get(path)
            if not entry:raise LookupError('书籍音频未登记。')
            target=safe_path(folder/'audio',path)
            if not target.is_file():raise LookupError('书籍音频文件不存在。')
            if digest(target.read_bytes())!=entry['sha256']:raise StorageError('书籍音频校验失败。')
            return target

    def save_audio(self,bid,cid,paragraphs,path,metadata,suppressed_id=None):
        """Merge into the latest chapter/state under the same store lock."""
        with self.locks.locked():
            b=self.load(bid)
            ch=next((c for c in b['chapters'] if c['id']==cid),None)
            if not ch:raise LookupError('章节已不存在。')
            current=[block['text_ja'] for block in ch['blocks'] if block.get('text_ja')]
            if current!=paragraphs:raise StorageError('章节原文已变化，请重新生成朗读。')
            versions = ch.setdefault('audio_versions', [])
            previous = ch.get('audio')
            if previous and previous not in versions:
                versions.append(deepcopy(previous))
            versions[:] = [v for v in versions if v.get('path') != metadata['path']]
            versions.append(deepcopy(metadata))
            ch.update(audio=metadata,voice_mode='browser' if metadata['voice_id'] is None else 'voice',
                      voice_id=metadata['voice_id'],voice_selected=True)
            if suppressed_id is not None:ch['audio_task_suppressed_id']=suppressed_id
            if b.get('progress',{}).get('chapter_id')==cid:
                b['progress']['audio_time']=0
            return self.save(b,audio_files={metadata['path']:path},tts=True)

    def backup(self,bid,reason):
        folder=self.folder(bid);dest=self.data/'backups'/f"book-{bid}-{reason}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        shutil.copytree(folder,dest)
        return dest

    def remove(self,bid):
        with self.locks.locked():
            folder=self.folder(bid)
            destination=self.data/'backups'/f"book-{bid}-removed-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
            if folder.exists():os.replace(folder,destination)
            with db_connection(self.db) as db:db.execute('DELETE FROM books WHERE id=?',(bid,))

    def refresh(self):
        with self.locks.locked():
            self.recover();invalid=[];missing=[];count=0
            with db_connection(self.db) as db:rows=[dict(r) for r in db.execute('SELECT * FROM books')]
            for row in rows:
                folder=safe_path(self.root,row['directory'])
                try:
                    if not stat.S_ISDIR(folder.stat().st_mode):raise ValueError('书籍路径不是目录')
                except FileNotFoundError:missing.append(row)
                except (OSError,ValueError) as e:invalid.append({'id':row['id'],'message':str(e)})
            backup=None
            if missing:
                backup=self.data/'backups'/f"books-missing-directories-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
                write_json(backup,{'books':missing})
                with db_connection(self.db) as db:db.executemany('DELETE FROM books WHERE id=?',[(r['id'],) for r in missing])
            seen={};valid=[]
            inaccessible={r['directory'] for r in rows if any(e.get('id')==r['id'] for e in invalid)}
            for folder in self.root.iterdir():
                if folder.name in inaccessible:continue
                try:
                    if not folder.is_dir() or not (folder/'book.json').exists():continue
                    meta=json.loads((folder/'book.json').read_text(encoding='utf-8'));bid=meta['book']['id']
                    if bid in seen:raise ValueError('重复书籍 ID')
                    seen[bid]=folder
                    for ch in meta['book']['chapters']:
                        if digest(safe_path(folder,ch['file']).read_bytes())!=ch['sha256']:raise ValueError('章节文件损坏')
                    valid.append(folder)
                except (ValueError,OSError,KeyError) as e:invalid.append({'directory':folder.name,'message':str(e)})
            if not invalid:
                for folder in valid:self._index(folder);count+=1
            return {'books_scanned':max(len(rows),count),'books_removed':len(missing),'removed_book_ids':[r['id'] for r in missing],
                    'invalid_book_records':invalid,'book_records_backup':backup.relative_to(self.data).as_posix() if backup else None}
