"""In-memory FIFO synthesis queue and immutable voice revisions."""
from __future__ import annotations

import atexit
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import unicodedata
import uuid
import wave

from article_store import write_json, safe_path, digest

ACTIVE = ('queued', 'running', 'cancelling')


class VoiceStore:
    def __init__(self, data):
        self.data = Path(data)
        self.root = self.data/'voices'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    @staticmethod
    def _name(value):
        name = unicodedata.normalize('NFC', str(value or '').strip())
        if not name or len(name) > 80:
            raise ValueError('声线名称须为 1–80 个字符。')
        if name in ('.', '..') or name.rstrip(' .') != name:
            raise ValueError('声线名称不能以空格或句点结尾。')
        if any(char in '<>:"/\\|?*\x00' or ord(char) < 32 for char in name):
            raise ValueError('声线名称不能包含 Windows 文件名禁用字符。')
        if name.upper() in {'CON', 'PRN', 'AUX', 'NUL'} or name.upper().startswith(('COM', 'LPT')) and name[3:].isdigit():
            raise ValueError('声线名称不能使用 Windows 保留名称。')
        return name

    @staticmethod
    def _id(name):
        # The API still uses numeric IDs, but the name is the only source of truth.
        return int(hashlib.sha256(name.encode('utf-8')).hexdigest()[:12], 16)

    @staticmethod
    def _previous_name_id(name):
        return int(hashlib.sha256(name.encode('utf-8')).hexdigest()[:15], 16)

    def _path(self, name):
        return safe_path(self.root, self._name(name) + '.wav')

    def _item(self, path):
        name = self._name(path.stem)
        blob = path.read_bytes()
        import soundfile as sf
        try:
            info = sf.info(str(path))
        except RuntimeError as error:
            raise ValueError(f'声线文件无法解码：{path.name}') from error
        if not info.samplerate or not info.frames:
            raise ValueError(f'声线文件为空：{path.name}')
        return {'id': self._id(name), 'name': name, 'file': path.name,
                'sha256': digest(blob), 'duration': info.frames/info.samplerate}

    def list(self):
        with self.lock:
            voices = [self._item(path) for path in self.root.glob('*.wav') if path.is_file()]
            ids = [voice['id'] for voice in voices]
            if len(ids) != len(set(ids)):
                raise ValueError('声线名称 ID 冲突，请修改其中一个名称。')
            return sorted(voices, key=lambda voice: (voice['name'].casefold(), voice['name']))

    def get(self, vid):
        item = next((v for v in self.list() if v['id'] == int(vid)), None)
        if not item:
            raise LookupError('声线不存在。')
        return item

    def reference(self, voice):
        path = self._path(voice['name'])
        if not path.is_file() or digest(path.read_bytes()) != voice['sha256']:
            raise ValueError('声线文件缺失或校验失败，请重新上传。')
        return path

    def migrate_legacy(self):
        """Flatten the former manifest/ID layout once, retaining a full backup."""
        with self.lock:
            legacy = self.root/'voices.json'
            if not legacy.exists():
                return {}
            try:
                entries = json.loads(legacy.read_text(encoding='utf-8')).get('voices', [])
            except (OSError, ValueError) as error:
                raise ValueError('旧声线注册表无法读取，未迁移任何声线。') from error
            plans = []
            for entry in entries:
                name = self._name(entry.get('name'))
                source = safe_path(self.root, entry.get('file', ''))
                if not source.is_file():
                    raise ValueError(f'旧声线文件缺失：{name}')
                target = self._path(name)
                if target.exists() and digest(target.read_bytes()) != digest(source.read_bytes()):
                    raise ValueError(f'无法迁移声线“{name}”：目标文件已存在且内容不同。')
                plans.append((int(entry['id']), name, source, target))
            archive = self.data/'backups'/f'voice-storage-layout-{uuid.uuid4().hex}'
            archive.mkdir(parents=True)
            shutil.copytree(self.root, archive/'voices')
            for _, _, source, target in plans:
                if source != target and not target.exists():
                    temporary = target.with_suffix('.tmp')
                    shutil.copyfile(source, temporary)
                    os.replace(temporary, target)
            for _, _, source, target in plans:
                if source != target:
                    source.unlink()
            legacy.unlink()
            for folder in sorted((path for path in self.root.iterdir() if path.is_dir()), reverse=True):
                try:
                    folder.rmdir()
                except OSError:
                    pass
            return {old: self._id(name) for old, name, _, _ in plans}

    def migrate_name_ids(self):
        """Repair IDs created before numeric values were made JavaScript-safe."""
        with self.lock:
            return {self._previous_name_id(path.stem): self._id(path.stem)
                    for path in self.root.glob('*.wav') if self._previous_name_id(path.stem) != self._id(path.stem)}

    def save(self, name, blob=None, vid=None):
        name = self._name(name)
        audio_blob = None
        if blob is not None:
            if not blob or len(blob) > 20*1024*1024:
                raise ValueError('参考音频须为 20 MB 以内的非空文件。')
            import numpy as np
            import soundfile as sf
            try:
                with sf.SoundFile(io.BytesIO(blob)) as source:
                    seconds = len(source)/source.samplerate
                    if not 1 <= seconds <= 120 or source.channels > 2 or source.samplerate > 192000:
                        raise ValueError('参考音频需为 1–120 秒、单声道或双声道。')
                    audio = source.read(dtype='float32', always_2d=True).mean(axis=1)
                    rate = source.samplerate
                if not np.isfinite(audio).all() or float(np.abs(audio).max()) < 1e-5:
                    raise ValueError('参考音频为空、静音或损坏。')
                output = io.BytesIO()
                sf.write(output, audio, rate, format='WAV', subtype='PCM_16')
                audio_blob = output.getvalue()
            except (RuntimeError, OSError) as error:
                raise ValueError('无法解码参考音频，请使用 WAV、MP3、FLAC 或 OGG。') from error
        with self.lock:
            if vid is None:
                if audio_blob is None:
                    raise ValueError('请选择参考音频。')
                if self._path(name).exists():
                    raise ValueError('已有同名声线，请使用其他名称。')
                previous = None
            else:
                previous = self.get(vid)
                old_path = self._path(previous['name'])
                target = self._path(name)
                if target != old_path and target.exists():
                    raise ValueError('已有同名声线，请使用其他名称。')
            target = self._path(name)
            if audio_blob is not None:
                temporary = target.with_suffix('.tmp')
                temporary.write_bytes(audio_blob)
                os.replace(temporary, target)
                if previous and target != old_path:
                    old_path.unlink(missing_ok=True)
            elif previous and target != old_path:
                os.replace(old_path, target)
            item = self._item(target)
            if previous:
                item['previous_id'] = previous['id']
            return item

    def remove(self, vid):
        with self.lock:
            item = self.get(vid)
            archive = self.data/'backups'/f'voice-{vid}-{uuid.uuid4().hex}'
            archive.mkdir(parents=True)
            shutil.copy2(self._path(item['name']), archive/(item['name'] + '.wav'))
            self._path(item['name']).unlink()


class ProcessBackend:
    def __init__(self, root, data):
        self.root, self.data = Path(root), Path(data)
        self.model = self.root/'Irodori-TTS/model/model.safetensors'
        self.process = None
        self.workspace = None
        self.log = None
        self.state = 'unloaded'
        self.error = ''
        self.verified = False
        self.lifecycle_lock = threading.RLock()

    def identity(self):
        # Checkpoint content hash is cached per backend; no repeated 3 GB reads.
        stat = self.model.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if getattr(self, '_signature', None) != signature:
            hasher = hashlib.sha256()
            with self.model.open('rb') as stream:
                for block in iter(lambda: stream.read(8*1024*1024), b''):
                    hasher.update(block)
            self._identity, self._signature = hasher.hexdigest(), signature
        return self._identity

    def _start(self, update, cancelled):
        if self.process and self.process.poll() is None:
            return
        self.close()
        self.workspace = Path(tempfile.mkdtemp(prefix='fujimi-tts-worker-'))
        logs = self.root/'logs'
        logs.mkdir(exist_ok=True)
        self.log = (logs/'tts-worker.log').open('a', encoding='utf-8')
        self.state, self.error = 'loading', ''
        update(stage='loading', message='Irodori モデルを読み込んでいます…')
        self.process = subprocess.Popen([sys.executable, '-X', 'utf8', str(self.root/'tts_worker.py'),
            '--workspace', str(self.workspace), '--model', str(self.model)], cwd=self.root,
            stdout=self.log, stderr=self.log, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 300
        while not (self.workspace/'ready.json').exists():
            if cancelled():
                self.close()
                raise InterruptedError()
            if self.process.poll() is not None or time.monotonic() > deadline:
                self.close()
                raise RuntimeError('Irodori 模型加载失败或超时，请检查 logs/tts-worker.log。')
            time.sleep(.15)
        result = json.loads((self.workspace/'ready.json').read_text(encoding='utf-8'))
        if result.get('error'):
            self.close()
            raise RuntimeError(result['error'])
        self.state = 'ready'

    def synthesize(self, request, directory, update, cancelled):
        try:
            self._start(update, cancelled)
            self.state = 'synthesizing'
            write_json(self.workspace/'request.json', dict(request, directory=str(directory)))
            previous = None
            deadline = time.monotonic() + 600
            while not (directory/'result.json').exists():
                if cancelled():
                    (directory/'cancel').touch(exist_ok=True)
                progress = directory/'progress.json'
                if progress.exists():
                    value = json.loads(progress.read_text(encoding='utf-8'))
                    if value != previous:
                        update(**value)
                        previous = value
                        deadline = time.monotonic() + 600
                if self.process.poll() is not None or time.monotonic() > deadline:
                    self.close()
                    raise RuntimeError('合成进程退出或单段处理超时，请重试。')
                time.sleep(.15)
            result = json.loads((directory/'result.json').read_text(encoding='utf-8'))
            if cancelled() or result.get('cancelled'):
                raise InterruptedError()
            if result.get('error'):
                raise RuntimeError(result['error'])
            self.verified, self.error = True, ''
            self.state = 'ready'
            return directory/'audio.wav', result
        except InterruptedError:
            if self.process:
                self.state = 'ready'
            raise
        except Exception as error:
            self.error = str(error)
            self.close()
            self.state = 'failed'
            raise

    def close(self):
        with self.lifecycle_lock:
            process, self.process = self.process, None
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
            if self.log:
                self.log.close()
                self.log = None
            self.state = 'unloaded'
            if self.workspace and self.workspace.exists():
                shutil.rmtree(self.workspace)
            self.workspace = None


class TTSQueue:
    def __init__(self, data, backend, commit, idle_seconds=300):
        self.temporary = tempfile.TemporaryDirectory(prefix='fujimi-tts-tasks-')
        self.root = Path(self.temporary.name)
        self.backend, self.commit, self.idle_seconds = backend, commit, idle_seconds
        self.lock = threading.RLock()
        self.tasks, self.requests = {}, {}
        self.queue = queue.Queue()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name='fujimi-tts-queue', daemon=True)
        self.thread.start()
        atexit.register(self.close)

    def _save(self, task):
        return None

    def get(self, tid):
        with self.lock:
            if tid not in self.tasks:
                raise LookupError('朗读任务不存在。')
            return deepcopy(self.tasks[tid])

    def latest(self, target):
        with self.lock:
            matching = [t for t in self.tasks.values() if t['target'] == target]
            return deepcopy(max(matching, key=lambda t: t['created_at'])) if matching else None

    def list(self):
        with self.lock:
            return deepcopy(list(self.tasks.values()))

    def submit(self, target, request, cache_key, **extra):
        with self.lock:
            latest = self.latest(target)
            if latest and latest['status'] in ('queued', 'running'):
                if latest['cache_key'] != cache_key:
                    raise ValueError('此内容正在生成其他声线，请先中止再重试。')
                return latest
            tid = uuid.uuid4().hex
            task = dict(id=tid, kind='tts', target=target, cache_key=cache_key, status='queued', stage='queued',
                completed=0, total=0, percent=0, message='朗読の順番を待っています…',
                created_at=time.time_ns(), **extra)
            self.tasks[tid], self.requests[tid] = task, request
            (self.root/tid).mkdir()
            self.queue.put(tid)
            return deepcopy(task)

    def cancel(self, tid):
        with self.lock:
            task = self.tasks.get(tid)
            if not task:
                raise LookupError('朗读任务不存在。')
            if task['status'] in ACTIVE:
                task.update(status='cancelled', stage='cancelled', message='已取消；当前分段返回后释放合成队列。')
                self._save(task)
            return deepcopy(task)

    def _run(self):
        while not self.stopping.is_set():
            try:
                tid = self.queue.get(timeout=self.idle_seconds)
            except queue.Empty:
                self.backend.close()
                continue
            if tid is None:
                break
            request = self.requests.pop(tid)
            task = self.tasks[tid]
            def cancelled():
                return self.stopping.is_set() or task['status'] == 'cancelled'
            def update(**values):
                with self.lock:
                    if cancelled():
                        return
                    task.update(values)
                    task['percent'] = min(99, round(task['completed']/max(1, task['total'])*100))
                    self._save(task)
            try:
                if cancelled():
                    continue
                update(status='running')
                path, result = self.backend.synthesize(request, self.root/tid, update, cancelled)
                with self.lock:
                    if cancelled():
                        continue
                    update(stage='saving', message='音声を保存しています…', completed=result['completed'], total=result['total'])
                    with wave.open(str(path), 'rb') as audio:
                        duration = audio.getnframes()/audio.getframerate()
                        if audio.getnframes() <= 0 or audio.getnchannels() != 1 or abs(duration-sum(s['duration'] for s in result['segments'])) > .002:
                            raise ValueError('合成音频与段落时间不匹配。')
                    self.commit(task, request, path, result)
                    remove_segment_files(request['segment_directory'], request['voice_name'])
                    task.update(status='completed', stage='complete', message='朗読の準備が完了しました。', percent=100)
                    self._save(task)
            except InterruptedError:
                with self.lock:
                    if not cancelled():
                        task.update(status='interrupted', stage='interrupted', message='朗读生成已中断，请重试。')
                        self._save(task)
            except Exception as error:
                with self.lock:
                    if not cancelled():
                        task.update(status='failed', stage='failed', message=str(error))
                        self._save(task)
            finally:
                shutil.rmtree(self.root/tid, ignore_errors=True)
                self.queue.task_done()
        self.backend.close()

    def close(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        self.queue.put(None)
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.backend.close()
            self.thread.join(timeout=2)
        self.temporary.cleanup()
        atexit.unregister(self.close)


def remove_segment_files(segment_directory, voice_name):
    directory = Path(segment_directory)
    for path in directory.glob(f'{voice_name}_segment_*.wav'):
        path.unlink(missing_ok=True)
    (directory/f'{voice_name}_segment_manifest.json').unlink(missing_ok=True)


def cache_key(paragraphs, model, voice):
    return digest(json.dumps({'text': paragraphs, 'model': model, 'voice': voice['sha256'], 'voice_name': voice['name'],
        'steps': 40, 'format': 'pcm16-48k-mono', 'split_version': 2}, ensure_ascii=False, sort_keys=True).encode('utf-8'))


def text_key(paragraphs):
    return digest(json.dumps(paragraphs, ensure_ascii=False).encode('utf-8'))
