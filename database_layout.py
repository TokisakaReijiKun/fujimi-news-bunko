"""Database layout checks shared by runtime and offline migration tools."""
from contextlib import closing
from pathlib import Path
import sqlite3


def has_legacy_articles(path):
    path = Path(path).resolve()
    if not path.exists():
        return False
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        return 'payload' in {row[1] for row in db.execute('PRAGMA table_info(articles)')}


def check_database_layout(data):
    data = Path(data)
    if any((data/'databases'/name).exists() for name in ('fujimi.sqlite3', 'dictionary-search.sqlite3')):
        raise ValueError('数据库仍在 databases 子目录，请停服务后运行 scripts/migrate_storage.py --apply。')
    if has_legacy_articles(data/'fujimi.sqlite3'):
        raise ValueError('检测到旧版正文 payload，请运行 scripts/migrate_storage.py --apply。')
