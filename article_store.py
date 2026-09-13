"""File-authoritative article storage with a rebuildable SQLite index."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import uuid
from database_layout import check_database_layout


CST = timezone(timedelta(hours=8))
_LOCKS = {}
_GUARD = threading.Lock()
TEXT_FIELDS = ('paragraphs', 'translated_paragraphs', 'furigana_paragraphs', 'original_text', 'full_translation')


class StorageError(ValueError):
    pass


def digest(content):
    return hashlib.sha256(content).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def safe_path(root, relative):
    relative = str(relative)
    if '\\' in relative or ':' in relative or relative.startswith('/') or '..' in relative.split('/'):
        raise StorageError('不安全的相对路径。')
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise StorageError('文件路径超出文章目录。')
    return path


def first_day(article, fallback):
    try:
        value = datetime.fromisoformat(article.get('created_at', '').replace('Z', '+00:00'))
        return value.replace(tzinfo=CST).date().isoformat() if value.tzinfo is None else value.astimezone(CST).date().isoformat()
    except (ValueError, TypeError):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', fallback or ''):
            return fallback
        raise StorageError('文章缺少可用的首次采集日期。')


def directory_name(title, aid, max_length=65):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip().rstrip(' .') or '未命名文章'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)', name, re.I):
        name = '_' + name
    if len(name) > max_length:
        suffix = f'--{aid}'
        name = name[:max_length-len(suffix)].rstrip(' .') + suffix
    return name


@contextmanager
def db_connection(path):
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class ArticleStore:
    def __init__(self, data, initialize=True):
        self.data = Path(data).resolve()
        self.root = self.data / 'articles'
        self.db_path = self.data / 'fujimi.sqlite3'
        self.transactions = self.data / 'diagnostics/transactions'
        with _GUARD:
            self._lock = _LOCKS.setdefault(str(self.data), threading.RLock())
        self._local = threading.local()
        if initialize:
            check_database_layout(self.data)
            for folder in (self.root, self.db_path.parent, self.transactions, self.data/'backups', self.data/'diagnostics/reports'):
                folder.mkdir(parents=True, exist_ok=True)
            with self.locked():
                self.recover()
                with db_connection(self.db_path) as db:
                    cols = [r['name'] for r in db.execute('PRAGMA table_info(articles)')]
                    if 'payload' in cols:
                        raise StorageError('检测到旧新闻存储，请先执行迁移工具。')
                    db.executescript('''CREATE TABLE IF NOT EXISTS articles(
                        id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, directory TEXT UNIQUE NOT NULL,
                        title TEXT NOT NULL, source_name TEXT NOT NULL, status TEXT NOT NULL,
                        bookmarked INTEGER NOT NULL, created_at TEXT, revision INTEGER NOT NULL);
                        CREATE TABLE IF NOT EXISTS article_days(article_id INTEGER NOT NULL, day TEXT NOT NULL,
                            PRIMARY KEY(article_id,day));
                        CREATE TABLE IF NOT EXISTS article_sequence(singleton INTEGER PRIMARY KEY CHECK(singleton=1), next_id INTEGER NOT NULL);
                        INSERT OR IGNORE INTO article_sequence VALUES(1,1);''')
                self.startup_report = self.rebuild()

    @contextmanager
    def locked(self):
        """One data-root lock serializes readers, writers, rebuilds and repair CLI."""
        with self._lock:
            depth = getattr(self._local, 'depth', 0)
            self._local.depth = depth + 1
            handle = None
            try:
                if depth == 0:
                    self.transactions.mkdir(parents=True, exist_ok=True)
                    handle = (self.transactions / '.lock').open('a+b')
                    handle.seek(0, 2)
                    if handle.tell() == 0:
                        handle.write(b'0'); handle.flush()
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_EX)
                    self.recover()
                yield
            finally:
                self._local.depth = depth
                if handle:
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_UN)
                    handle.close()

    def recover(self):
        if not self.transactions.exists(): return
        for journal in self.transactions.glob('*/journal.json'):
            record = json.loads(journal.read_text(encoding='utf-8'))
            target = safe_path(self.root, record['target'])
            stage, old = journal.parent/'new', journal.parent/'old'
            if stage.exists():
                # No committed new directory: restore the previous version.
                if old.exists() and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(old, target)
            elif target.exists():
                # Directory switch completed. Index is derived and reconciled below.
                try:
                    self._index(target, self._read(target))
                except sqlite3.OperationalError as error:
                    if 'no such table' not in str(error):
                        raise  # Retain journal; never hide an unavailable index.
            elif old.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old, target)
            else:
                raise StorageError(f'无法恢复文章事务：{journal.parent.name}')
            shutil.rmtree(journal.parent)

    def allocate_directory(self, article, day, reserved=None):
        day = first_day(article, day)
        # Reserve room for media/audio filenames on Windows under this long workspace.
        maximum = min(65, 225 - len(str(self.root/day)) - 45)
        if maximum < 12: raise StorageError('数据根目录路径过长，请使用较短的 FUJIMI_DATA_DIR。')
        name = directory_name(article['title'], article['id'], maximum)
        reserved = reserved or set()
        existing = {p.name.casefold() for p in (self.root/day).iterdir()} if (self.root/day).exists() else set()
        if name.casefold() in existing or f'{day}/{name}'.casefold() in reserved:
            suffix = f"--{article['id']}"
            name = name[:maximum-len(suffix)].rstrip(' .') + suffix
        if name.casefold() in existing or f'{day}/{name}'.casefold() in reserved:
            raise StorageError('文章目录发生冲突，未覆盖现有文件。')
        return f'{day}/{name}'

    def _read(self, directory, verify_media=False):
        manifest = json.loads((directory/'article.json').read_text(encoding='utf-8'))
        if manifest.get('schema_version') != 1 or not isinstance(manifest.get('article', {}).get('id'), int):
            raise StorageError('不支持的文章文件格式。')
        article = deepcopy(manifest['article'])
        if set(manifest.get('text_files',{})) != {'original.txt','translation.txt','furigana.html'}:
            raise StorageError('文章缺少必要的文本文件描述。')
        for filename, spec in manifest['text_files'].items():
            blob = safe_path(directory, filename).read_bytes()
            if digest(blob) != spec['sha256']:
                raise StorageError(f'{filename} 校验失败；原文或译文被外部修改。')
            text = blob.decode('utf-8')
            def portion(span):
                start, end = span
                if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= len(text):
                    raise StorageError('段落字符区间无效。')
                return text[start:end]
            article[spec['field']] = [portion(span) for span in spec['paragraphs']]
            if spec.get('whole_field'):
                article[spec['whole_field']] = portion(spec['whole_span'])
        article['_revision'] = manifest['revision']
        article['_directory'] = directory.relative_to(self.root).as_posix() if directory.is_relative_to(self.root) else ''
        article['_assets'] = manifest.get('assets', [])
        registered = {asset['path'] for asset in article['_assets']}
        references = list(article.get('image_paths',[])) + [p for p in article.get('video_urls',[]) if not p.startswith(('http://','https://'))]
        if article.get('audio_path'): references.append(article['audio_path'])
        if any(p not in registered for p in references):
            raise StorageError('文章引用了未登记的附件。')
        for asset in article['_assets']:
            path = safe_path(directory, asset['path'])
            if asset['path'].split('/')[0] not in ('media', 'audio'):
                raise StorageError('附件必须位于 media 或 audio。')
            if verify_media and (not path.is_file() or digest(path.read_bytes()) != asset['sha256']):
                raise StorageError(f"附件缺失或校验失败：{asset['path']}")
        return article

    def _index(self, directory, article):
        with db_connection(self.db_path) as db:
            db.execute('''INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                url=excluded.url,directory=excluded.directory,title=excluded.title,source_name=excluded.source_name,
                status=excluded.status,bookmarked=excluded.bookmarked,created_at=excluded.created_at,revision=excluded.revision''',
                (article['id'], article.get('storage_key') or article.get('url') or f"local:{article['id']}",
                 directory.relative_to(self.root).as_posix(), article['title'], article.get('source_name',''),
                 article.get('status','ready'), int(article.get('bookmarked',False)), article.get('created_at',''), article['_revision']))
            db.execute('DELETE FROM article_days WHERE article_id=?', (article['id'],))
            db.executemany('INSERT INTO article_days VALUES(?,?)', [(article['id'], day) for day in article.get('edition_dates',[])])
            db.execute('UPDATE article_sequence SET next_id=MAX(next_id,?) WHERE singleton=1', (article['id']+1,))

    def rebuild(self):
        with self.locked():
            valid, errors, ids, urls = [], [], {}, {}
            for manifest in sorted(self.root.glob('*/*/article.json')):
                try:
                    a = self._read(manifest.parent, verify_media=True)
                    key = a.get('storage_key') or a.get('url') or f"local:{a['id']}"
                    if a['id'] in ids or key in urls:
                        raise StorageError('重复文章 ID 或 URL；索引重建已停止。')
                    ids[a['id']], urls[key] = manifest, manifest
                    valid.append((manifest.parent, a))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    errors.append({'directory':manifest.parent.relative_to(self.root).as_posix(), 'message':str(error)})
            report = {'scanned':len(valid)+len(errors),'indexed':0,'errors':errors}
            if not errors:
                with db_connection(self.db_path) as db:
                    db.execute('DELETE FROM article_days'); db.execute('DELETE FROM articles')
                    for directory, a in valid:
                        key = a.get('storage_key') or a.get('url') or f"local:{a['id']}"
                        db.execute('INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?)', (a['id'], key,
                            directory.relative_to(self.root).as_posix(),a['title'],a.get('source_name',''),a.get('status','ready'),
                            int(a.get('bookmarked',False)),a.get('created_at',''),a['_revision']))
                        db.executemany('INSERT INTO article_days VALUES(?,?)', [(a['id'],day) for day in a.get('edition_dates',[])])
                    db.execute('UPDATE article_sequence SET next_id=MAX(next_id,?) WHERE singleton=1', (max(ids,default=0)+1,))
                report['indexed'] = len(valid)
            write_json(self.data/'diagnostics/reports/article-index.json', report)
            return report

    def load(self, aid):
        with self.locked():
            with db_connection(self.db_path) as db:
                row = db.execute('SELECT directory FROM articles WHERE id=?',(aid,)).fetchone()
            if not row:
                self.rebuild()
                with db_connection(self.db_path) as db:
                    row = db.execute('SELECT directory FROM articles WHERE id=?',(aid,)).fetchone()
            if not row: raise LookupError('文章不存在。')
            return self._read(safe_path(self.root, row['directory']))

    def find_url(self, url):
        with self.locked(), db_connection(self.db_path) as db:
            row = db.execute('SELECT id FROM articles WHERE url=?',(url,)).fetchone()
            return row['id'] if row else None

    def ids(self, day=None, bookmarked=False):
        with self.locked(), db_connection(self.db_path) as db:
            query, args = 'SELECT a.id FROM articles a WHERE 1=1', []
            if day:
                query += ' AND a.id IN (SELECT article_id FROM article_days WHERE day=?)'; args.append(day)
            if bookmarked: query += ' AND a.bookmarked=1'
            return [r[0] for r in db.execute(query+' ORDER BY a.id DESC',args)]

    def days(self):
        with self.locked(), db_connection(self.db_path) as db:
            return [r[0] for r in db.execute('SELECT DISTINCT day FROM article_days ORDER BY day DESC')]

    def create(self, article, day):
        with self.locked():
            key = article.get('storage_key') or article.get('url') or 'local:'+uuid.uuid4().hex
            existing = self.find_url(key)
            if existing:
                self.add_day(existing,day)
                return self.load(existing)
            with db_connection(self.db_path) as db:
                aid = db.execute('SELECT next_id FROM article_sequence WHERE singleton=1').fetchone()[0]
                db.execute('UPDATE article_sequence SET next_id=next_id+1 WHERE singleton=1')
            a = dict(article,id=aid,storage_key=key,edition_dates=[day],bookmarked=False)
            return self.save(a, directory=self.allocate_directory(a,day))

    def _texts(self, article):
        files, specs = {}, {}
        for filename, field, whole in [('original.txt','paragraphs','original_text'),
                                       ('translation.txt','translated_paragraphs','full_translation'),
                                       ('furigana.html','furigana_paragraphs',None)]:
            text, spans = '', []
            for index, part in enumerate(article.get(field, [])):
                if index: text += '\n\n'
                start = len(text); text += part; spans.append([start,len(text)])
            spec = {'field':field,'paragraphs':spans}
            if whole:
                full = article.get(whole, text)
                start = text.find(full)
                if start < 0:
                    # Preserve unusual legacy whole-text representations exactly.
                    text += '\n\n'; start = len(text); text += full
                spec.update(whole_field=whole,whole_span=[start,start+len(full)])
            files[filename] = text.encode('utf-8')
            spec['sha256'] = digest(files[filename]); specs[filename] = spec
        return files, specs

    def save(self, article, directory=None, files=None):
        with self.locked():
            a = deepcopy(article)
            duplicate = self.find_url(a.get('storage_key') or a.get('url') or f"local:{a['id']}")
            if duplicate and duplicate != a['id']:
                raise StorageError('URL 已属于另一篇文章。')
            existing = None
            if directory is None:
                existing = self.load(a['id'])
                directory = existing['_directory']
                if a.get('_revision') != existing['_revision']:
                    raise StorageError('文章已被另一任务更新，请重试。')
            target = safe_path(self.root,directory)
            tx = self.transactions/uuid.uuid4().hex
            stage = tx/'new'; stage.mkdir(parents=True)
            try:
                if target.exists():
                    if existing is None: raise StorageError('目标目录已存在。')
                    shutil.copytree(target,stage,dirs_exist_ok=True)
                for folder in ('media','audio'): (stage/folder).mkdir(exist_ok=True)
                for relative, source in (files or {}).items():
                    dest = safe_path(stage,relative)
                    if relative.split('/')[0] not in ('media','audio'): raise StorageError('无效附件路径。')
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,dest)
                text_files,specs = self._texts(a)
                for filename,blob in text_files.items():
                    with (stage/filename).open('wb') as stream:
                        stream.write(blob);stream.flush();os.fsync(stream.fileno())
                assets = deepcopy(a.pop('_assets', []))
                for item in assets:
                    blob = safe_path(stage,item['path']).read_bytes()
                    item.update(sha256=digest(blob),bytes=len(blob))
                metadata = {k:v for k,v in a.items() if k not in TEXT_FIELDS and not k.startswith('_')}
                revision = (existing['_revision'] if existing else 0)+1
                manifest = {'schema_version':1,'revision':revision,'article':metadata,'text_files':specs,'assets':assets}
                write_json(stage/'article.json',manifest)
                # Validate all referenced text/media before exposing the replacement.
                self._read(stage,verify_media=True)
                write_json(tx/'journal.json',{'target':directory})
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists(): os.replace(target,tx/'old')
                os.replace(stage,target)
                self._index(target,self._read(target))
                shutil.rmtree(tx)
            except Exception:
                if (tx/'journal.json').exists(): self.recover()
                elif tx.exists(): shutil.rmtree(tx)
                raise
            return self.load(a['id'])

    def patch(self, aid, updates):
        with self.locked():
            a = self.load(aid); a.update(updates); return self.save(a)

    def add_day(self, aid, day):
        with self.locked():
            a = self.load(aid)
            if day not in a.get('edition_dates',[]):
                a.setdefault('edition_dates',[]).append(day); self.save(a)

    def wire(self, article):
        a = {k:v for k,v in article.items() if not k.startswith('_') and k != 'storage_key'}
        prefix = f"/api/articles/{a['id']}/assets/"
        a['image_paths'] = [prefix+p for p in a.get('image_paths',[])]
        a['video_urls'] = [prefix+p if p.startswith(('media/','audio/')) else p for p in a.get('video_urls',[])]
        if a.get('audio_path','').startswith('audio/'): a['audio_path'] = prefix+a['audio_path']
        return a

    def asset(self, aid, relative):
        with self.locked():
            a = self.load(aid)
            if relative not in {v['path'] for v in a['_assets']} or a.get('status') == 'excluded_paid':
                raise LookupError('附件不存在。')
            path = safe_path(self.root/a['_directory'],relative)
            if not path.is_file(): raise LookupError('附件不存在。')
            return path

    def legacy_asset(self, filename):
        for aid in self.ids():
            a = self.load(aid)
            for asset in a['_assets']:
                if filename in asset.get('legacy_names',[]): return self.asset(aid,asset['path'])
        raise LookupError('媒体文件不存在。')

    def attach_cached(self, aid, cached, cache_root):
        with self.locked():
            a = self.load(aid)
            files, assets = {}, [v for v in a['_assets'] if v['path'].startswith('audio/')]
            image_paths, videos = [], []
            for kind, names in [('image',cached['image_paths']),('video',cached['video_urls'])]:
                for i,name in enumerate(names,1):
                    old = name.removeprefix('/api/media/')
                    relative = f'media/{kind}-{i:03d}{Path(old).suffix.lower()}'
                    files[relative] = safe_path(cache_root,old)
                    item = {'path':relative,'kind':kind,'legacy_names':[old]}
                    if kind=='image':
                        for key, field in [('caption','image_captions'),('position','image_positions'),('source_url','image_urls'),('original_link','image_links')]:
                            item[key] = cached[field][i-1]
                        image_paths.append(relative)
                    else: videos.append(relative)
                    assets.append(item)
            a.update(cached,image_paths=image_paths,video_urls=videos,_assets=assets)
            return self.save(a,files=files)
