"""Bounded sharing-violation retries for the temporary TTS file protocol."""
import json
import os
from pathlib import Path
import time
import uuid


def _retry_permission(operation):
    # A Windows reader may briefly deny a concurrent atomic replacement (and
    # vice versa). Keep waits short and bounded; do not change file permissions.
    for attempt in range(6):
        try:
            return operation()
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(min(.025 * 2 ** attempt, .2))


def read_json(path):
    return json.loads(_retry_permission(lambda: Path(path).read_text(encoding='utf-8')))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        _retry_permission(lambda: os.replace(temporary, path))
    finally:
        if temporary.exists():
            _retry_permission(lambda: temporary.unlink(missing_ok=True))
