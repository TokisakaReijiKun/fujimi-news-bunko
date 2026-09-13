"""Back up and re-extract explicitly selected local article records."""
import argparse
from collections import Counter
from datetime import datetime
import json
import os
import shutil
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_config import load_local_config
from server import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ids', type=int, nargs='+', required=True)
    parser.add_argument('--apply', action='store_true', help='Apply repair after a SQLite backup; otherwise list selected records')
    args = parser.parse_args()
    data = Path(os.environ.get('FUJIMI_DATA_DIR', ROOT / 'data'))
    app = create_app(data)
    store = app.article_store
    db_path = store.db_path
    rows = [(aid, store.load(aid)) for aid in sorted(set(args.ids))]
    if len(rows) != len(set(args.ids)):
        raise SystemExit('Some requested article IDs do not exist.')
    if not args.apply:
        for aid, article in rows:
            print(aid, article['edition_dates'], article['source_name'], article['title'])
        return
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_folder = data / 'backups' / ('before-article-extraction-' + stamp)
    backup_folder.mkdir(parents=True)
    backup_path = backup_folder / 'fujimi.sqlite3'
    for aid, article in rows:
        source = store.root / article['_directory']
        shutil.copytree(source, backup_folder / 'articles' / article['_directory'])
    with sqlite3.connect(db_path) as db, sqlite3.connect(backup_path) as backup:
        db.backup(backup)
    db.close()
    backup.close()
    print('Backup:', backup_path.name, flush=True)
    load_local_config(ROOT)
    results = []
    for aid, _ in rows:
        try:
            article = app.fujimi_repair_article(aid)
            result = {'id':aid, 'status':article['status'], 'paragraphs':len(article['paragraphs']),
                      'translations':sum(bool(p) for p in article.get('translated_paragraphs', [])),
                      'images':len(article.get('image_paths', [])), 'media_warnings':article.get('media_warnings', []),
                      'failure_reason':article.get('failure_reason', '')}
        except Exception as e:
            result = {'id':aid, 'status':'repair_failed', 'error':str(e)}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    # A historic edition must not continue claiming all quotas are satisfied.
    with sqlite3.connect(db_path) as db:
        task = db.execute("SELECT value FROM settings WHERE key='daily-result'").fetchone()
        if task:
            task = json.loads(task[0])
            day = task.get('date')
            if day in {day for _, article in rows for day in article['edition_dates']}:
                values = [store.load(aid) for aid in store.ids(day=day)]
                ready = [a for a in values if a.get('status') == 'ready']
                counts = Counter(a['source_name'] for a in ready)
                sources = json.loads(db.execute("SELECT value FROM settings WHERE key='news-sources'").fetchone()[0])
                missing = [s['name'] for s in sources if counts[s['name']] < s.get('minimum_count', 0)]
                target = json.loads(db.execute("SELECT value FROM settings WHERE key='daily-content'").fetchone()[0])['target_count']
                complete = not missing and len(ready) >= target
                task.update(status='completed' if complete else 'partial', stage='complete' if complete else 'partial',
                            source_counts=dict(counts), missing_sources=missing, completed=len(ready), total=target,
                            percent=100 if complete else min(99, round(len(ready)/max(1,target)*100)),
                            message=f'校正后日刊 {len(ready)}/{target} 篇。' + ('缺少可公开阅读的来源：'+'、'.join(missing) if missing else ''))
                db.execute("UPDATE settings SET value=? WHERE key='daily-result'", (json.dumps(task,ensure_ascii=False),))
    db.close()
    report = data / 'diagnostics/reports' / ('article-repair-' + stamp + '.json')
    report.write_text(json.dumps({'backup':backup_path.name, 'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    if any(r['status'] == 'repair_failed' for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
