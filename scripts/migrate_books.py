"""Offline, backed-up conversion of the old book payloads into book directories."""
import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from article_store import db_connection,write_json,directory_name,digest
from book_store import BookStore
from epub_parser import parse_epub


def transfer_state(old,new):
    """Keep anchors by source file + exact paragraph; don't reuse obsolete indexes."""
    old_chapters={c['id']:c for c in old['chapters']}
    positions=[]
    for chapter in new['chapters']:
        for block in chapter['blocks']:
            positions.append((chapter['id'],block))
    def locate(chapter_id,index):
        oldchapter=old_chapters.get(chapter_id)
        if not oldchapter:return None
        blocks=oldchapter.get('blocks',[]);block=blocks[min(max(0,int(index)),len(blocks)-1)] if blocks else {}
        source=oldchapter.get('source_href','');text=block.get('text_ja','').strip()
        candidates=[(cid,b) for cid,b in positions if b.get('source_href')==source]
        if not candidates:return None
        exact=next(((cid,b) for cid,b in candidates if text and text in (b.get('text_ja','').strip(),b.get('text_zh','').strip())),None)
        cid,b=exact or min(candidates,key=lambda pair:abs(pair[1].get('source_block_index',0)-int(index)))
        return cid,b['block_index']
    progress=deepcopy(old.get('progress',{}))
    if progress:
        target=locate(progress.get('chapter_id'),progress.get('block_index',0))
        if target:progress.update(chapter_id=target[0],block_index=target[1],scroll_offset=0,scroll_left=0,audio_time=0)
        else:progress={}
    bookmarks=[]
    for mark in old.get('bookmarks',[]):
        target=locate(mark.get('chapter_id'),mark.get('block_index',0))
        if target:bookmarks.append(dict(mark,chapter_id=target[0],block_index=target[1]))
    new.update(progress=progress,bookmarks=bookmarks,last_read_at=old.get('last_read_at',''),imported_at=old['imported_at'],
               series=old.get('series',''),volume=old.get('volume',''))
    # Reuse translations from unchanged source paragraphs; bilingual EPUB text wins.
    translations={b.get('text_ja'):b.get('text_zh') for c in old['chapters'] for b in c['blocks'] if b.get('text_zh')}
    for _,block in positions:
        if not block['text_zh']:block['text_zh']=translations.get(block['text_ja'],'')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,default=Path(os.environ.get('FUJIMI_DATA_DIR',ROOT/'data')))
    p.add_argument('--book-id',type=int);p.add_argument('--epub',type=Path);p.add_argument('--apply',action='store_true')
    args=p.parse_args();data=args.data_dir.resolve();dbpath=data/'fujimi.sqlite3'
    with db_connection(dbpath) as db:
        cols={r['name'] for r in db.execute('PRAGMA table_info(books)')}
        if 'payload' not in cols:print('书架已经使用文件存储。');return
        rows=[dict(r) for r in db.execute('SELECT * FROM books')]
    for row in rows:print(row['id'],json.loads(row['payload'])['title'].strip())
    if not args.apply:return
    if bool(args.epub)!=bool(args.book_id):raise ValueError('--epub 与 --book-id 必须一起提供。')
    backup=data/'backups'/('book-storage-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
    with db_connection(dbpath) as before,db_connection(backup/'fujimi.sqlite3') as after:before.backup(after)
    if (data/'books').exists():shutil.copytree(data/'books',backup/'books')
    prepared=[]
    for row in rows:
        old=json.loads(row['payload']);blob=None
        if row['id']==args.book_id:
            blob=args.epub.read_bytes();b,assets=parse_epub(blob,args.epub.name);transfer_state(old,b)
            # Progress is mapped to the new parser version so browser session caches cannot override it.
            b['reading_revision']=2
        else:
            b=old;assets={path.relative_to(data/'books'/str(row['id'])).as_posix():path.read_bytes() for path in (data/'books'/str(row['id'])).rglob('*') if path.is_file()}
            b.update(original_available=False,parser_version=1,reading_revision=1,
                     warnings=['旧导入未保存原始 EPUB；请重新导入原文件以恢复正式目录。'])
            b['toc']=[{'id':c['id'],'title':c['title'],'chapter_id':c['id'],'depth':0,'anchor':'','block_index':0} for c in b['chapters']]
        b['id']=row['id'];b['title']=b['title'].strip();b['author']=b.get('author','').strip()
        prepared.append((row,b,assets,blob))
    created=[]
    try:
        with db_connection(dbpath) as db:db.execute('DROP TABLE books')
        store=BookStore(data)
        for row,b,assets,blob in prepared:
            name=directory_name(b['title'],b['id'],55)
            if (store.root/name).exists():name=name[:45]+'--'+str(b['id'])
            created.append(store.root/name)
            store.save(b,directory=name,assets=assets,original=blob,digest_value=digest(blob) if blob else row['digest'])
            check=store.load(b['id'])
            if len(check['chapters'])!=len(b['chapters']):raise ValueError('章节验证失败')
        retained=[]
        for row,_,_,_ in prepared:
            old=data/'books'/str(row['id'])
            if old.exists():
                try:os.replace(old,backup/('retired-'+str(row['id'])))
                except PermissionError:retained.append(old.relative_to(data).as_posix())
        write_json(data/'diagnostics/reports/book-migration.json',{'backup':backup.relative_to(data).as_posix(),'ids':[r['id'] for r in rows],'retained_legacy_directories':retained})
        print('迁移完成，备份：',backup.name)
    except Exception:
        for directory in created:
            if directory.exists():os.replace(directory,backup/('failed-'+directory.name))
        with db_connection(backup/'fujimi.sqlite3') as src,db_connection(dbpath) as dst:src.backup(dst)
        raise


if __name__=='__main__':main()
