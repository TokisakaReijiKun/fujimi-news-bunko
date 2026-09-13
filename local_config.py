"""Load local secrets; process environment overrides the ignored .env file."""
import os
from pathlib import Path


def load_local_config(root):
    path = Path(root) / '.env'
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        key, separator, value = line.partition('=')
        if separator and key.strip() in ('DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL'):
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ.setdefault(key.strip(), value)
