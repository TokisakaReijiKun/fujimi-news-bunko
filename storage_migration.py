"""Explicit, offline migration of legacy article payloads into article folders."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3

from article_store import ArticleStore, StorageError, db_connection, digest, safe_path, write_json
from database_layout import has_legacy_articles


def flatten_databases(data, apply=False):
    """Move only known databases and sidecars; never overwrite root files."""
    data = Path(data).resolve()
    folder = data/'databases'
    moves, errors = [], []
    if has_legacy_articles(folder/'fujimi.sqlite3'):
        errors.append('子目录数据库仍包含旧正文 payload，需先单独处理。')
    for name in ('fujimi.sqlite3', 'dictionary-search.sqlite3'):
        for suffix in ('', '-wal', '-shm', '-journal'):
            source = folder/(name+suffix)
            if source.exists():
                moves.append({'source':'databases/'+source.name, 'destination':source.name})
                if (data/source.name).exists():
                    errors.append('目标文件已存在，拒绝覆盖：'+source.name)
    result = {'status':'flatten_databases', 'moves':moves, 'errors':errors,
              'unknown_files':[p.name for p in folder.iterdir() if p.name not in {Path(m['source']).name for m in moves}] if folder.exists() else []}
    if not apply: return result
    if errors: raise StorageError('；'.join(errors))
    if not moves: return result
    backup = data/'backups'/('database-relocation-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    for move in moves:
        source = safe_path(data, move['source'])
        shutil.copy2(source,backup/source.name)
    result.update(backup=backup.relative_to(data).as_posix(),status='prepared')
    write_json(backup/'relocation.json',result)
    moved=[]
    try:
        for move in moves:
            os.replace(safe_path(data,move['source']),safe_path(data,move['destination']))
            moved.append(move)
    except BaseException:
        for move in reversed(moved):
            os.replace(safe_path(data,move['destination']),safe_path(data,move['source']))
        raise
    if not any(folder.iterdir()): folder.rmdir()
    result['status']='flattened'
    write_json(backup/'relocation.json',result)
    write_json(data/'diagnostics/reports/database-relocation.json',result)
    return result


def legacy_rows(data):
    path = Path(data)/'fujimi.sqlite3'
    if not path.exists(): return []
    connection = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute('SELECT * FROM articles ORDER BY id')]
    finally:
        connection.close()


def legacy_article(row):
    a = json.loads(row['payload'])
    a.update(id=row['id'],bookmarked=bool(row['bookmarked']),storage_key=row['url'],edition_dates=[row['day']])
    return a


def attachment_plan(data, article):
    data = Path(data)
    mappings = []
    for kind, values in [('image',article.get('image_paths',[])),('video',article.get('video_urls',[])),
                         ('audio',[article['audio_path']] if article.get('audio_path') else [])]:
        for index, value in enumerate(values,1):
            if value.startswith(('http://','https://')):
                continue
            if kind == 'audio':
                relative = value.removeprefix('/api/audio/')
                source = safe_path(data/'audio',relative)
            else:
                relative = value.removeprefix('/api/media/')
                source = safe_path(data/'media',relative)
            ext = source.suffix.lower()
            destination = f'audio/legacy/audio-{index:03d}{ext}' if kind=='audio' else f'media/{kind}-{index:03d}{ext}'
            mappings.append({'kind':kind,'index':index-1,'source':source.relative_to(data).as_posix(),
                             'path':destination,'legacy_name':relative,'exists':source.is_file()})
    return mappings


def preview(data):
    data = Path(data).resolve()
    if any((data/'databases'/name).exists() for name in ('fujimi.sqlite3','dictionary-search.sqlite3')):
        return flatten_databases(data)
    if not (data/'fujimi.sqlite3').exists():
        return {'status':'empty', 'articles':[], 'errors':[]}
    if not has_legacy_articles(data/'fujimi.sqlite3'):
        return {'status':'already_migrated', 'articles':[], 'errors':[]}
    store = ArticleStore(data,initialize=False)
    reserved, articles, errors, urls = set(), [], [], set()
    for row in legacy_rows(data):
        try:
            a = legacy_article(row)
            if row['url'] in urls: raise StorageError('重复 URL')
            urls.add(row['url'])
            directory = store.allocate_directory(a,row['day'],reserved)
            reserved.add(directory.casefold())
            attachments = attachment_plan(data,a)
            for item in attachments:
                if not item['exists']: errors.append({'id':a['id'],'message':'附件缺失：'+item['source']})
            articles.append({'id':a['id'],'directory':directory,'title':a['title'],'attachments':attachments})
        except (ValueError, OSError, KeyError) as error:
            errors.append({'id':row['id'],'message':str(error)})
    recognized = []
    unknown = []
    for path in data.iterdir():
        name = path.name
        if name in ('articles','databases','backups','diagnostics','books'): continue
        if name in ('fujimi.sqlite3','fujimi.sqlite3-wal','fujimi.sqlite3-shm'):
            continue  # Switched separately before exposing the new index.
        if name in ('media','audio'):
            recognized.append({'source':name,'destination':'migration backup'})
        elif name == 'dictionary-search.sqlite3': continue
        elif name == 'inspection': recognized.append({'source':name,'destination':'diagnostics/inspection'})
        elif name.startswith('before-') and name.endswith('.sqlite3'): recognized.append({'source':name,'destination':'backups/'+name})
        elif name.startswith('article-repair-') and name.endswith('.json'): recognized.append({'source':name,'destination':'diagnostics/reports/'+name})
        else: unknown.append(name)
    return {'status':'pending','articles':articles,'errors':errors,'relocations':recognized,'unknown_files':unknown}


def verify_equal(old, new):
    for field in ('id','title','url','source_name','status','bookmarked','paragraphs','translated_paragraphs',
                  'furigana_paragraphs','original_text','full_translation','edition_dates'):
        default = [] if field.endswith('paragraphs') or field=='edition_dates' else ''
        if old.get(field,default) != new.get(field,default):
            raise StorageError(f"文章 {old['id']} 迁移不一致：{field}")


def migrate(data):
    data = Path(data).resolve()
    if any((data/'databases'/name).exists() for name in ('fujimi.sqlite3','dictionary-search.sqlite3')):
        return flatten_databases(data,apply=True)
    active = data/'backups/storage-migration-active.json'
    if active.exists():
        backup = safe_path(data,json.loads(active.read_text(encoding='utf-8'))['backup'])
        state = json.loads((backup/'migration.json').read_text(encoding='utf-8'))
        if state['phase']=='complete': return state
    else:
        plan = preview(data)
        if plan['status'] != 'pending': return plan
        if plan['errors']: raise StorageError('迁移预检失败：'+json.dumps(plan['errors'],ensure_ascii=False))
        if (data/'articles').exists() and any((data/'articles').iterdir()): raise StorageError('目标 articles 非空，拒绝覆盖。')
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup = data/'backups'/('storage-migration-'+stamp)
        backup.mkdir(parents=True)
        state = {'phase':'backup','backup':backup.relative_to(data).as_posix(),'plan':plan,'original_entries':[]}
        write_json(backup/'migration.json',state)
        write_json(active,{'backup':state['backup']})
    snapshot = backup/'original'
    snapshot.mkdir(exist_ok=True)
    if state['phase']=='backup':
        for path in data.iterdir():
            if path.name in ('backups','databases','articles','diagnostics') or path.name.endswith(('-wal','-shm')): continue
            dest = snapshot/path.name
            if not dest.exists():
                if path.name == 'fujimi.sqlite3':
                    with db_connection(path) as src, db_connection(dest) as dst: src.backup(dst)
                elif path.is_dir(): shutil.copytree(path,dest)
                else: shutil.copy2(path,dest)
            if path.name not in state['original_entries']: state['original_entries'].append(path.name)
        state['phase']='building';write_json(backup/'migration.json',state)
    # Build the replacement database and article tree away from the active paths.
    work = data/'diagnostics/migration-work'
    if state['phase']=='building':
        work.mkdir(parents=True,exist_ok=True)
        new_db = work/'fujimi.sqlite3'
        if not new_db.exists():
            with db_connection(snapshot/'fujimi.sqlite3') as src, db_connection(new_db) as dst:
                src.backup(dst)
                dst.execute('DROP TABLE articles')
        store = ArticleStore(work)
        rows = {row['id']:row for row in legacy_rows(snapshot)}
        for item in state['plan']['articles']:
            a = legacy_article(rows[item['id']])
            existing = store.ids()
            if a['id'] in existing:
                verify_equal(a,store.load(a['id']));continue
            assets, files = [], {}
            a['image_paths'] = list(a.get('image_paths',[]))
            a['video_urls'] = list(a.get('video_urls',[]))
            for attachment in item['attachments']:
                source = safe_path(snapshot,attachment['source'])
                relative,kind,i = attachment['path'],attachment['kind'],attachment['index']
                files[relative] = source
                asset = {'path':relative,'kind':kind,'legacy_names':[attachment['legacy_name']],
                         'sha256':digest(source.read_bytes())}
                if kind=='image':
                    a['image_paths'][i] = relative
                    for key,field in [('caption','image_captions'),('position','image_positions'),('source_url','image_urls'),('original_link','image_links')]:
                        values = a.get(field,[]);asset[key] = values[i] if i<len(values) else (-1 if key=='position' else '')
                elif kind=='video': a['video_urls'][i] = relative
                else: a['audio_path'] = relative
                assets.append(asset)
            a['_assets'] = assets
            saved = store.save(a,directory=item['directory'],files=files)
            verify_equal(legacy_article(rows[item['id']]),saved)
        report = store.rebuild()
        if report['errors'] or report['indexed']!=len(rows): raise StorageError('迁移后的文件校验失败。')
        with db_connection(snapshot/'fujimi.sqlite3') as before, db_connection(new_db) as after:
            for table in ('settings','books'):
                if [tuple(r) for r in before.execute(f'SELECT * FROM {table} ORDER BY 1')] != [tuple(r) for r in after.execute(f'SELECT * FROM {table} ORDER BY 1')]:
                    raise StorageError(table+' 数据被改变。')
        with db_connection(new_db) as db:
            db.execute('VACUUM')
        state['phase']='switching';write_json(backup/'migration.json',state)
    if state['phase']=='switching':
        if has_legacy_articles(data/'fujimi.sqlite3'):
            retired = backup/'retired'
            retired.mkdir(exist_ok=True)
            for suffix in ('-wal','-shm','-journal',''):
                old = data/('fujimi.sqlite3'+suffix)
                if old.exists():
                    if (retired/old.name).exists(): raise StorageError('旧数据库归档冲突。')
                    os.replace(old,retired/old.name)
        for source,target in [(work/'articles',data/'articles'),(work/'fujimi.sqlite3',data/'fujimi.sqlite3')]:
            if source.exists():
                if target.exists():
                    if target.is_dir() and not any(target.iterdir()): target.rmdir()
                    else: raise StorageError('切换目标发生冲突。')
                os.replace(source,target)
        store = ArticleStore(data)
        if store.startup_report['errors']: raise StorageError('切换后验证失败。')
        state['phase']='organizing';write_json(backup/'migration.json',state)
    if state['phase']=='organizing':
        for item in state['plan']['relocations']:
            if item['source'] in ('fujimi.sqlite3','fujimi.sqlite3-wal','fujimi.sqlite3-shm','dictionary-search.sqlite3'):
                continue
            source = safe_path(data,item['source'])
            if not source.exists():continue
            relative = item['destination']
            target = backup/'retired'/item['source'] if relative=='migration backup' else safe_path(data,relative)
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():raise StorageError('归类目标已存在：'+str(target))
            os.replace(source,target)
        # Work directory is retained with the migration backup, not scattered in diagnostics.
        if work.exists():os.replace(work,backup/'work')
        state['phase']='complete';write_json(backup/'migration.json',state)
        write_json(data/'diagnostics/reports/storage-migration.json',state)
    return state


def rollback(data):
    data = Path(data).resolve()
    active = data/'backups/storage-migration-active.json'
    if not active.exists():raise StorageError('没有可回滚的迁移记录。')
    backup = safe_path(data,json.loads(active.read_text(encoding='utf-8'))['backup'])
    state = json.loads((backup/'migration.json').read_text(encoding='utf-8'))
    archive = backup/('rollback-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    archive.mkdir()
    # Preserve all post-migration writes before restoring the old version.
    for name in ('articles','databases','diagnostics','fujimi.sqlite3','fujimi.sqlite3-wal','fujimi.sqlite3-shm',
                 'fujimi.sqlite3-journal','dictionary-search.sqlite3','dictionary-search.sqlite3-wal','dictionary-search.sqlite3-shm'):
        source = data/name
        if source.exists():os.replace(source,archive/name)
    for name in state['original_entries']:
        source = backup/'original'/name
        target = data/name
        if target.exists():os.replace(target,archive/name)
        if source.is_dir():shutil.copytree(source,target)
        else:shutil.copy2(source,target)
    state['phase']='rolled_back';write_json(backup/'migration.json',state)
    active.unlink()
    return {'status':'rolled_back','preserved_new_data':archive.relative_to(data).as_posix()}
