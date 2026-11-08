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

from article_store import safe_path, digest
from tts_protocol import read_json, write_json

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

    @classmethod
    def validate_synced(cls, name, blob, *, verify_content=True):
        """Validate an existing WAV reference without changing its bytes."""
        name = cls._name(name)
        if not isinstance(blob, bytes) or not blob or len(blob) > 20 * 1024 * 1024:
            raise ValueError('参考音频须为 20 MB 以内的非空文件。')
        if blob[:4] != b'RIFF' or blob[8:12] != b'WAVE':
            raise ValueError('同步声线必须是有效 WAV 文件。')
        import numpy as np
        import soundfile as sf
        try:
            with sf.SoundFile(io.BytesIO(blob)) as source:
                seconds = len(source) / source.samplerate
                if (source.format not in ('WAV', 'WAVEX') or not 1 <= seconds <= 120
                        or not 1 <= source.channels <= 2 or not 0 < source.samplerate <= 192000):
                    raise ValueError('参考音频需为 1–120 秒、单声道或双声道 WAV。')
                audio = source.read(dtype='float32', always_2d=True).mean(axis=1)
            if not np.isfinite(audio).all() or not audio.size or float(np.abs(audio).max()) < 1e-5:
                raise ValueError('参考音频为空、静音或损坏。')
        except (RuntimeError, OSError) as error:
            raise ValueError('无法解码同步声线 WAV。') from error
        return {'id': cls._id(name), 'name': name, 'file': name + '.wav',
                **({'sha256': digest(blob)} if verify_content else {}), 'duration': seconds}

    def import_synced(self, name, blob, *, compare_size=False):
        """Atomically add a validated reference; existing names are never overwritten."""
        item = self.validate_synced(name, blob, verify_content=not compare_size)
        with self.lock:
            target = self._path(item['name'])
            if compare_size:
                existing = next((path for path in self.root.glob('*.wav')
                                 if path.is_file() and path.stem.casefold() == item['name'].casefold()), None)
                if existing:
                    same = existing.name == target.name and existing.stat().st_size == len(blob)
                    return dict(id=self._id(existing.stem), name=existing.stem, file=existing.name,
                                status='unchanged' if same else 'conflict')
                existing = None
            else:
                existing = next((voice for voice in self.list()
                                 if voice['name'].casefold() == item['name'].casefold()), None)
            if existing:
                same = existing['name'] == item['name'] and existing['sha256'] == item['sha256']
                return dict(existing, status='unchanged' if same else 'conflict')
            temporary = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                with temporary.open('xb') as output:
                    output.write(blob)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return dict(item, status='created')

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

    @staticmethod
    def _decode_m4a(blob):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            raise ValueError('导入 M4A 参考音频需要本机安装 ffmpeg。')
        with tempfile.TemporaryDirectory(prefix='fujimi-voice-') as directory:
            source = Path(directory)/'source.m4a'
            output = Path(directory)/'decoded.wav'
            source.write_bytes(blob)
            try:
                subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-protocol_whitelist', 'file',
                                '-i', str(source), '-map', '0:a:0', '-vn', '-t', '121',
                                '-ac', '1', '-ar', '48000', '-c:a', 'pcm_s16le', str(output)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.SubprocessError) as error:
                raise ValueError('无法解码 M4A 参考音频，请确认文件包含有效音轨。') from error
            return output.read_bytes()

    def save(self, name, blob=None, vid=None):
        name = self._name(name)
        audio_blob = None
        if blob is not None:
            if not blob or len(blob) > 20*1024*1024:
                raise ValueError('参考音频须为 20 MB 以内的非空文件。')
            import numpy as np
            import soundfile as sf
            try:
                if len(blob) >= 12 and blob[4:8] == b'ftyp':
                    blob = self._decode_m4a(blob)
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
                raise ValueError('无法解码参考音频，请使用 WAV、MP3、FLAC、OGG 或 M4A。') from error
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


class WorkerLoadExit(RuntimeError):
    """Unexpected native exit before the worker completed its handshake."""


class ProcessBackend:
    def __init__(self, root, data, python_executable=None):
        self.root, self.data = Path(root), Path(data)
        self.python_executable = str(python_executable or sys.executable)
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
        for attempt in range(2):
            if cancelled():
                raise InterruptedError()
            try:
                return self._start_once(update, cancelled)
            except WorkerLoadExit:
                if attempt or cancelled():
                    if cancelled():
                        raise InterruptedError()
                    raise
                update(stage='loading', message='模型进程意外退出，正在重新加载（1/1）…')

    def _diagnostic(self, event):
        if self.log:
            print(f'[worker {time.strftime("%Y-%m-%d %H:%M:%S")}] {event}',
                  file=self.log, flush=True)

    def _start_once(self, update, cancelled):
        if self.process and self.process.poll() is None:
            return
        self.close()
        self.workspace = Path(tempfile.mkdtemp(prefix='fujimi-tts-worker-'))
        logs = self.root/'logs'
        logs.mkdir(exist_ok=True)
        self.log = (logs/'tts-worker.log').open('a', encoding='utf-8')
        self.state, self.error = 'loading', ''
        update(stage='loading', message='Irodori モデルを読み込んでいます…')
        self.process = subprocess.Popen([self.python_executable, '-u', '-X', 'utf8', str(self.root/'tts_worker.py'),
            '--workspace', str(self.workspace), '--model', str(self.model)], cwd=self.root,
            stdout=self.log, stderr=self.log, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._diagnostic(f'start pid={self.process.pid}')
        deadline = time.monotonic() + 300
        while not (self.workspace/'ready.json').exists():
            if cancelled():
                self.close()
                raise InterruptedError()
            code = self.process.poll()
            if code is not None or time.monotonic() > deadline:
                # The child may publish a structured error just before exiting.
                if (self.workspace/'ready.json').exists():
                    break
                stage = 'imports'
                progress = self.workspace/'loading.json'
                if progress.exists():
                    stage = read_json(progress).get('stage', stage)
                pid = self.process.pid
                self._diagnostic(f'load ended pid={pid} exit={code} stage={stage}')
                self.close()
                if code is not None:
                    raise WorkerLoadExit(f'Irodori 加载进程退出：{code} (0x{code & 0xffffffff:08X})；阶段 {stage}；PID {pid}。请检查 logs/tts-worker.log。')
                raise RuntimeError(f'Irodori 模型加载超过 300 秒；阶段 {stage}。请检查 logs/tts-worker.log。')
            time.sleep(.15)
        result = read_json(self.workspace/'ready.json')
        if result.get('error'):
            self.close()
            raise RuntimeError(result['error'])
        self.state = 'ready'
        self._diagnostic(f'ready pid={self.process.pid}')

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
                    value = read_json(progress)
                    if value != previous:
                        update(**value)
                        previous = value
                        deadline = time.monotonic() + 600
                if self.process.poll() is not None or time.monotonic() > deadline:
                    self.close()
                    raise RuntimeError('合成进程退出或单段处理超时，请重试。')
                time.sleep(.15)
            result = read_json(directory/'result.json')
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
                self._diagnostic(f'stop pid={process.pid}')
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
    def __init__(self, data, backend, commit, idle_seconds=3000):
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
