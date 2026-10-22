"""Seed one synthetic phone-only article on the isolated acceptance emulator."""
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from article_store import ArticleStore

adb = 'C:/Android/Sdk/platform-tools/adb.exe'
serial = 'emulator-5554'
with tempfile.TemporaryDirectory(prefix='fujimi-sync-phone-') as temporary:
    store = ArticleStore(Path(temporary))
    store.create(dict(title='Reserved fixture ID', paragraphs=['予約。'], url='https://example.test/reserved'), '2026-10-17')
    article = store.create(dict(title='同步验收・Androidから', paragraphs=['これはスマートフォンから同期した本文です。'],
        translated_paragraphs=['这是从手机同步的正文。'], furigana_paragraphs=[], source_name='同步验收', status='ready',
        url='https://example.test/device-sync/android', created_at='2026-10-17T11:00:00+08:00'), '2026-10-17')
    destination = '/storage/emulated/0/富士見新聞文庫/data/articles/2026-10-17'
    subprocess.run([adb, '-s', serial, 'shell', 'mkdir', '-p', destination], check=True, timeout=20)
    source = Path(temporary) / 'phone-fixture'
    shutil.copytree(store.root / article['_directory'], source)
    for empty in ('audio', 'media'):
        (source / empty).rmdir()
    subprocess.run([adb, '-s', serial, 'push', str(source), '/data/local/tmp/'], check=True, timeout=30)
    subprocess.run([adb, '-s', serial, 'shell', 'cp', '-r', '/data/local/tmp/phone-fixture', destination + '/'], check=True, timeout=20)
