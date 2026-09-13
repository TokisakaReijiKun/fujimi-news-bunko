"""Offline storage migration. Default: read-only preview; --apply or --rollback mutates."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from storage_migration import preview, migrate, rollback

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('FUJIMI_DATA_DIR',ROOT/'data')))
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--apply',action='store_true')
    group.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    result=rollback(args.data_dir) if args.rollback else migrate(args.data_dir) if args.apply else preview(args.data_dir)
    print(json.dumps(result,ensure_ascii=False,indent=2))
