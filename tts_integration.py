"""Connect TTS to existing file stores and Flask without publisher-specific rules."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import uuid
import wave

from flask import jsonify, request, send_from_directory
from werkzeug.exceptions import Conflict, ServiceUnavailable

from article_store import write_json, digest
from tts_service import ACTIVE, VoiceStore, ProcessBackend, TTSQueue, cache_key, text_key, remove_segment_files


class TTSController:
    def __init__(self, app, root, data, articles, books, setting, download, enabled=False, backend=None, examples=None):
        self.app, self.root, self.data = app, Path(root), Path(data)
        self.articles, self.books, self.setting, self.download, self.examples = articles, books, setting, download, examples
        self.enabled = enabled or backend is not None
        self.lock = threading.RLock()
        self.queue = None
        self.error = ''
        if self.enabled:
            self.voices = VoiceStore(data)
            self.backend = backend or ProcessBackend(root, data)
            try:
                mapping = self.voices.migrate_legacy()
                mapping.update(self.voices.migrate_name_ids())
                self._migrate_voice_ids(mapping)
                self._initialize()
                self._migrate_book_audio_paths()
            except Exception as error:
                self.error = str(error)
            self.queue = TTSQueue(data, self.backend, self._commit)
        self._routes()

    def require(self):
        if not self.enabled:
            raise ServiceUnavailable('Irodori 未启用；请使用 Tokyo 启动本地服务。')
        if self.error:
            raise ServiceUnavailable(self.error)

    def _initialize(self):
        if self.setting('irodori-initialized-v1'):
            return
        backup = self.data/'backups'/f'tts-settings-{uuid.uuid4().hex}'
        backup.mkdir(parents=True)
        source = sqlite3.connect(self.data/'fujimi.sqlite3')
        target = sqlite3.connect(backup/'fujimi.sqlite3')
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        write_json(backup/'settings.json', {k: self.setting(k) for k in ('voice-mode', 'news-sources')})
        existing = next((v for v in self.voices.list() if v['name'] == '朽木冬子'), None)
        voice = existing or self.voices.save('朽木冬子', (self.root/'Irodori-TTS/朽木冬子.mp3').read_bytes())
        mode = self.setting('voice-mode')
        mode.update(mode='voice', voice_id=voice['id'])
        self.setting('voice-mode', mode)
        sources = self.setting('news-sources')
        for source in sources:
            if source['id'] <= 6:
                source.update(voice_mode='model', voice_id=None)
        self.setting('news-sources', sources)
        self.setting('irodori-initialized-v1', {'voice_id': voice['id'], 'backup': str(backup.relative_to(self.data))})

    def _migrate_voice_ids(self, mapping):
        """Move references when names replace the old ID/manifest source of truth."""
        mapping = {int(old): int(new) for old, new in mapping.items() if int(old) != int(new)}
        if not mapping:
            return
        def replace(value):
            return mapping.get(int(value), value) if value is not None else None
        mode = self.setting('voice-mode')
        if mode.get('voice_id') in mapping:
            mode['voice_id'] = replace(mode['voice_id'])
            self.setting('voice-mode', mode)
        sources = self.setting('news-sources')
        if any(source.get('voice_id') in mapping for source in sources):
            for source in sources:
                source['voice_id'] = replace(source.get('voice_id'))
            self.setting('news-sources', sources)
        marker = self.setting('irodori-initialized-v1')
        if isinstance(marker, dict) and marker.get('voice_id') in mapping:
            marker['voice_id'] = replace(marker['voice_id'])
            self.setting('irodori-initialized-v1', marker)
        for aid in self.articles.ids():
            article = self.articles.load(aid)
            if article.get('audio_voice_id') in mapping:
                # Existing audio remains where it was committed. New synthesis uses
                # the readable voice/title filename without moving active user files.
                try:
                    article['audio_voice_id'] = replace(article['audio_voice_id'])
                    self.articles.save_tts(article)
                except Exception as error:
                    self.app.logger.warning('Voice ID migration skipped article %s: %s', aid, error)
        for bid in self.books.ids():
            book = self.books.load(bid)
            changed = False
            for chapter in book['chapters']:
                if chapter.get('voice_id') in mapping:
                    chapter['voice_id'] = replace(chapter['voice_id'])
                    changed = True
                if isinstance(chapter.get('audio'), dict) and chapter['audio'].get('voice_id') in mapping:
                    chapter['audio']['voice_id'] = replace(chapter['audio']['voice_id'])
                    changed = True
            if changed:
                try:
                    self.books.save(book, tts=True)
                except Exception as error:
                    self.app.logger.warning('Voice ID migration skipped book %s: %s', bid, error)

    def _migrate_book_audio_paths(self):
        """Move legacy chapter UUID files into the readable book-level audio layout."""
        for bid in self.books.ids():
            book = self.books.load(bid)
            folder = self.books.folder(bid)
            updates, sources, old_paths, changed = {}, {}, set(), False
            occupied = {m.get('path') for c in book['chapters']
                        for m in [c.get('audio', {})] + c.get('audio_versions', []) if isinstance(m, dict)}
            occupied.update(p.name for p in (folder/'audio').glob('*.wav'))
            for chapter in book['chapters']:
                title = chapter.get('title') or f"第{chapter['id']}章"
                recordings = [chapter.get('audio', {})] + chapter.get('audio_versions', [])
                for metadata in recordings:
                    if not isinstance(metadata, dict):
                        continue
                    old = metadata.get('path', '')
                    source = folder/'audio'/old
                    if not re.fullmatch(r'\d+/[^/]+\.wav', old or ''):
                        continue
                    if old in updates:
                        new = updates[old]
                        metadata.update(path=new, url=f'/api/books/{bid}/audio/{new}')
                        changed = True
                        continue
                    if not source.is_file():
                        replacement = next((item for item in recordings if isinstance(item, dict)
                            and item is not metadata and item.get('task_id') == metadata.get('task_id')
                            and item.get('voice_id') == metadata.get('voice_id')
                            and item.get('path') and not re.fullmatch(r'\d+/[^/]+\.wav', item['path'])
                            and (folder/'audio'/item['path']).is_file()), None)
                        if replacement:
                            new = replacement['path']
                            updates[old] = new
                            old_paths.add(old)
                            metadata.update(path=new, url=f'/api/books/{bid}/audio/{new}')
                            changed = True
                        continue
                    voice = next((v for v in self.voices.list() if v['id'] == metadata.get('voice_id')), None)
                    if not voice:
                        continue
                    stem = self._book_audio_stem(voice['name'], title, chapter['id'], occupied)
                    new = f'{stem}.wav'
                    updates[old], sources[old] = new, source
                    old_paths.add(old)
                    occupied.add(new)
                    metadata['path'] = new
                    metadata['url'] = f'/api/books/{bid}/audio/{new}'
                    changed = True
            if not changed:
                continue
            backup = self.data/'backups'/f'tts-book-{bid}-{uuid.uuid4().hex}'
            backup.mkdir(parents=True)
            shutil.copytree(folder, backup/'book')
            source_db = sqlite3.connect(self.data/'fujimi.sqlite3')
            target_db = sqlite3.connect(backup/'fujimi.sqlite3')
            try:
                source_db.backup(target_db)
            finally:
                target_db.close()
                source_db.close()
            try:
                self.books.save(book, audio_files={updates[old]: source for old, source in sources.items()},
                                audio_remove=old_paths, tts=True)
                for old in old_paths:
                    (folder/'audio'/old).unlink(missing_ok=True)
            except Exception as error:
                self.app.logger.warning('Book %s audio migration skipped: %s', bid, error)

    def health(self):
        if not self.enabled:
            return {'enabled': False, 'state': 'disabled', 'inference_verified': False}
        return {'enabled': True, 'configured': (self.root/'Irodori-TTS/model/model.safetensors').is_file(),
            'state': self.backend.state, 'inference_verified': self.backend.verified,
            'error': self.error or self.backend.error,
            'queued': sum(t['status'] == 'queued' for t in self.queue.list())}

    def voice_list(self):
        if not self.enabled:
            return []
        mode = self.setting('voice-mode')
        return [dict(id=v['id'], name=v['name'], duration=v['duration'],
                     active=mode.get('mode') == 'voice' and mode.get('voice_id') == v['id']) for v in self.voices.list()]

    def resolve(self, payload):
        mode = payload.get('mode', 'model')
        vid = payload.get('voice_id')
        if mode in ('model', 'inherit'):
            selected = self.setting('voice-mode')
            mode, vid = selected['mode'], selected.get('voice_id')
        if mode in ('browser', 'none'):
            return mode, None
        self.require()
        if mode != 'voice' or not vid:
            raise ValueError('请选择有效的朗读声线。')
        voice = self.voices.get(vid)
        self.voices.reference(voice)
        return mode, voice

    def article_wire(self, article):
        result = self.articles.wire(article)
        task = self.queue.latest(f"article:{article['id']}") if self.queue else None
        if task and task['id'] != article.get('audio_task_suppressed_id'):
            result.update(audio_task_id=task['id'], audio_task_status=task['status'], audio_progress=task['completed'],
                          audio_total=task['total'], audio_task_detail=task['message'])
            if task['status'] in ACTIVE:
                result['audio_status'] = 'replacing' if result.get('audio_path') else 'pending' if task['status'] == 'queued' else 'processing'
            elif task['status'] in ('failed', 'interrupted'):
                result['audio_status'] = 'replace_failed' if result.get('audio_path') else 'failed'
            elif task['status'] == 'cancelled' and not result.get('audio_path') and result.get('audio_voice_mode') not in ('browser', 'none'):
                result['audio_status'] = 'disabled'
        return result

    def chapter_wire(self, bid, chapter):
        result = deepcopy(chapter)
        task = self.queue.latest(f"book:{bid}:{chapter['id']}") if self.queue else None
        if task and task['id'] != chapter.get('audio_task_suppressed_id'):
            result['audio_task'] = task
        if self.enabled and not result.get('audio') and not result.get('voice_selected'):
            result['voice_mode'] = 'model'
        return result

    @staticmethod
    def _browser_voice_label(name):
        if str(name).startswith(('kokoro:', 'voicevox:')):
            from browser_tts import browser_voice
            return browser_voice(name)['name']
        if 'Keita' in str(name): return '圭太'
        if 'Nanami' in str(name): return '七海'
        return str(name).removeprefix('Microsoft ').split(' - ', 1)[0].split(' Online', 1)[0]

    @staticmethod
    def _system_browser_wav(text, voice_name):
        with tempfile.TemporaryDirectory(prefix='fujimi-system-voice-') as directory:
            text_path, audio_path = Path(directory) / 'text.txt', Path(directory) / 'voice.wav'
            text_path.write_text(text, encoding='utf-8')
            command = (
                "param($textPath,$audioPath,$voiceName); "
                "Add-Type -AssemblyName System.Speech; "
                "$s=[System.Speech.Synthesis.SpeechSynthesizer]::new(); "
                "$v=$s.GetInstalledVoices() | ? {$_.Enabled -and $_.VoiceInfo.Name -eq $voiceName} | select -First 1; "
                "if (!$v) {$v=$s.GetInstalledVoices() | ? {$_.Enabled -and $_.VoiceInfo.Name -like ('*'+$voiceName.Split(' ')[1]+'*')} | select -First 1}; "
                "if (!$v) {throw 'voice unavailable'}; $s.SelectVoice($v.VoiceInfo.Name); $s.SetOutputToWaveFile($audioPath); "
                "$s.Speak([IO.File]::ReadAllText($textPath,[Text.Encoding]::UTF8)); $s.Dispose()"
            )
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-Command', command, str(text_path), str(audio_path), voice_name],
                capture_output=True, timeout=120, check=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            if result.returncode or not audio_path.is_file():
                raise ValueError('所选系统声线无法导出音频，请检查 Windows 语音包。')
            return audio_path.read_bytes()

    def _browser_audio(self, paragraphs, voice_name):
        voice_name = str(voice_name or '').strip()
        if not voice_name:
            raise ValueError('请先选择浏览器声线。')
        if voice_name in ('Microsoft Keita Online (Natural) - Japanese (Japan)',
                          'Microsoft Nanami Online (Natural) - Japanese (Japan)'):
            from desktop_edge_speech import synthesize_with_segments
            voice = 'ja-JP-KeitaNeural' if 'Keita' in voice_name else 'ja-JP-NanamiNeural'
            audio, segments = synthesize_with_segments('\n'.join(paragraphs), voice, paragraphs)
            return audio, segments, '.mp3'
        if voice_name.startswith(('kokoro:', 'voicevox:')):
            backend = self.app.extensions['browser_tts']
            chunks, durations = [], []
            for paragraph in paragraphs:
                chunk = backend.synthesize(paragraph, voice_name)
                with wave.open(io.BytesIO(chunk), 'rb') as source:
                    params = (source.getnchannels(), source.getsampwidth(), source.getframerate())
                    if params != (1, 2, 24000): raise ValueError('浏览器声线返回的音频格式不匹配。')
                    durations.append(source.getnframes() / source.getframerate())
                    chunks.append(source.readframes(source.getnframes()))
            output = io.BytesIO()
            with wave.open(output, 'wb') as merged:
                merged.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                for chunk in chunks: merged.writeframes(chunk)
            return output.getvalue(), [{'duration': value, 'speech_start_offset': 0} for value in durations], '.wav'
        audio = self._system_browser_wav('\n'.join(paragraphs), voice_name)
        with wave.open(io.BytesIO(audio), 'rb') as source:
            duration = source.getnframes() / source.getframerate()
        weights = [max(1, len(value.strip())) for value in paragraphs]
        total = sum(weights) or 1
        return audio, [{'duration': duration * weight / total, 'speech_start_offset': 0} for weight in weights], '.wav'

    def _save_browser_article(self, article, voice_name, suppressed_id=None):
        label = self._browser_voice_label(voice_name)
        suffix = '.mp3' if 'Online' in voice_name else '.wav'
        filename = self._article_audio_filename(label, article['title']).rsplit('.', 1)[0] + suffix
        relative = f'audio/{filename}'
        folder = self.articles.root / article['_directory']
        existing = folder / relative
        if not existing.is_file():
            audio, segments, actual_suffix = self._browser_audio(article['paragraphs'], voice_name)
            relative = f'audio/{Path(filename).stem}{actual_suffix}'
            with tempfile.NamedTemporaryFile(prefix='fujimi-browser-', suffix=actual_suffix, delete=False) as temporary:
                temporary.write(audio); source = Path(temporary.name)
            try:
                article.update(audio_path=relative, audio_segments=segments, audio_status='ready',
                               audio_voice_mode='browser', audio_voice_id=None,
                               audio_voice_name=voice_name, audio_task_suppressed_id=suppressed_id)
                saved = self.articles.save_tts(article, files={relative: source})
            finally: source.unlink(missing_ok=True)
            return {'status': 'ready'}
        article.update(audio_path=relative, audio_status='ready', audio_voice_mode='browser',
                       audio_voice_id=None, audio_voice_name=voice_name,
                       audio_task_suppressed_id=suppressed_id)
        saved = self.articles.save_tts(article)
        return {'status': 'ready', 'cached': True}

    def _save_browser_chapter(self, bid, cid, voice_name, suppressed_id=None):
        book, chapter = self.books.chapter(bid, cid)
        paragraphs = [block['text_ja'] for block in chapter['blocks'] if block.get('text_ja')]
        audio, segments, suffix = self._browser_audio(paragraphs, voice_name)
        occupied = {m.get('path') for c in book['chapters']
                    for m in [c.get('audio', {})] + c.get('audio_versions', []) if isinstance(m, dict)}
        stem = self._book_audio_stem(self._browser_voice_label(voice_name), chapter['title'], cid, occupied)
        filename = f'{stem}{suffix}'
        with tempfile.NamedTemporaryFile(prefix='fujimi-browser-', suffix=suffix, delete=False) as temporary:
            temporary.write(audio); source = Path(temporary.name)
        try:
            metadata = {'path': filename, 'url': f'/api/books/{bid}/audio/{filename}', 'status': 'ready',
                        'voice_id': None, 'voice_name': voice_name, 'segments': segments}
            self.books.save_audio(bid, cid, paragraphs, source, metadata, suppressed_id=suppressed_id)
        finally: source.unlink(missing_ok=True)
        return {'status': 'ready'}

    def auto_article(self, article, source=None):
        if not self.enabled:
            return article
        try:
            self.submit_article(article['id'], {'mode': (source or {}).get('voice_mode', 'model'),
                                'voice_id': (source or {}).get('voice_id'),
                                'browser_voice_name': (source or {}).get('browser_voice_name', ''),
                                'auto': True,
                                'example_id': article.get('example_id')})
        except Exception as error:
            # Audio failures never roll back a successfully imported article.
            latest = self.articles.load(article['id'])
            latest.update(audio_status='failed', audio_task_detail=str(error))
            self.articles.save_tts(latest)
        return self.articles.load(article['id'])

    def submit_article(self, aid, payload):
        with self.lock:
            mode, voice = self.resolve(payload)
            article = self.articles.load(aid)
            if article.get('status') != 'ready':
                raise Conflict('正文不可用，不能生成朗读。')
            if mode in ('browser', 'none'):
                previous = self.cancel_target(f'article:{aid}')
                browser_name = (payload.get('browser_voice_name') or article.get('example_browser_voice_name')
                                or self.setting('voice-mode').get('browser_voice_name', '')) if mode == 'browser' else ''
                if browser_name:
                    try:
                        result = self._save_browser_article(article, browser_name, previous.get('id'))
                        return result
                    except ValueError as error:
                        if not payload.get('auto'):
                            raise
                        article.update(audio_status='browser', audio_voice_mode='browser',
                                       audio_task_detail=str(error), audio_task_suppressed_id=previous.get('id'))
                        self.articles.save_tts(article)
                        return {'status': 'browser'}
                article.update(audio_status='browser' if mode == 'browser' else 'disabled',
                    audio_voice_mode=mode, audio_task_suppressed_id=previous.get('id'))
                self.articles.save_tts(article)
                return {'status': 'browser' if mode == 'browser' else 'disabled'}
            self.require()
            return self._submit(f'article:{aid}', article['paragraphs'], voice, article_id=aid,
                                example_id=payload.get('example_id') or article.get('example_id'))

    def submit_chapter(self, bid, cid, payload, configure_only=False):
        with self.lock:
            mode, voice = self.resolve(payload)
            if mode == 'browser' and not configure_only:
                browser_name = payload.get('browser_voice_name') or self.setting('voice-mode').get('browser_voice_name', '')
                if browser_name:
                    previous = self.cancel_target(f'book:{bid}:{cid}')
                    return self._save_browser_chapter(bid, cid, browser_name, previous.get('id'))
            if configure_only or mode in ('browser', 'none'):
                previous = self.cancel_target(f'book:{bid}:{cid}')
                with self.books.locks.locked():
                    b = self.books.load(bid)
                    chapter = next((c for c in b['chapters'] if c['id'] == cid), None)
                    if not chapter:
                        raise LookupError('章节不存在。')
                    chapter.update(voice_mode=payload.get('mode', mode) if configure_only else mode,
                                   voice_id=voice['id'] if voice else None, voice_selected=True,
                                   audio_task_suppressed_id=previous.get('id'))
                    self.books.save(b, tts=True)
                return {'status': mode}
            self.require()
            _, chapter = self.books.chapter(bid, cid)
            paragraphs = [b['text_ja'] for b in chapter['blocks'] if b.get('text_ja')]
            return self._submit(f'book:{bid}:{cid}', paragraphs, voice, book_id=bid, chapter_id=cid)

    @staticmethod
    def _matches_audio(metadata, paragraphs, voice):
        if not metadata or metadata.get('voice_id') != voice['id']:
            return False
        # Older selected audio has no text/reference fingerprint; retain its
        # registered identity. All new recordings carry both fingerprints.
        if metadata.get('voice_sha256', voice['sha256']) != voice['sha256']:
            return False
        if metadata.get('text_sha256', text_key(paragraphs)) != text_key(paragraphs):
            return False
        return len(metadata.get('segments', [])) == len(paragraphs)

    @staticmethod
    def _validate_audio(path, metadata):
        with wave.open(str(path), 'rb') as audio:
            duration = audio.getnframes() / audio.getframerate()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 48000):
                raise ValueError('已有朗读格式不匹配。')
            if duration <= 0 or abs(duration - sum(s['duration'] for s in metadata['segments'])) > .002:
                raise ValueError('已有朗读与段落时间不匹配。')

    def _reuse_audio(self, paragraphs, voice, **ids):
        if 'article_id' in ids:
            with self.articles.locked():
                article = self.articles.load(ids['article_id'])
                if article['paragraphs'] != paragraphs:
                    raise Conflict('文章原文已变化，请重试。')
                folder = self.articles.root / article['_directory']
                filename = self._article_audio_filename(voice['name'], article['title'])
                path = folder/'audio'/filename
                if not path.is_file():
                    path = next((item for item in sorted((folder/'audio').iterdir())
                                 if item.is_file() and item.suffix == path.suffix
                                 and item.stem.startswith(path.stem + '-')), None)
                if path:
                    relative = path.relative_to(folder).as_posix()
                    segments = article.get('audio_segments', []) if article.get('audio_path') == relative else []
                    article.update(audio_path=relative, audio_segments=segments,
                        audio_status='ready', audio_voice_id=voice['id'], audio_voice_mode='voice',
                        audio_cache_key=None)
                    self.articles.save_tts(article)
                    return True
                if article.get('example_id') and self.examples:
                    cached = self.examples.cached_audio(article['example_id'], voice['id'], text_key(paragraphs))
                    if cached:
                        source, metadata = cached
                        if not self._matches_audio(metadata, paragraphs, voice):
                            return False
                        try:
                            self._validate_audio(source, metadata)
                        except (OSError, ValueError, EOFError, wave.Error):
                            return False
                        relative = f"audio/{filename}"
                        article.update(audio_path=relative, audio_segments=metadata['segments'], audio_status='ready',
                            audio_voice_id=voice['id'], audio_voice_mode='voice', audio_cache_key=metadata.get('cache_key'))
                        self.articles.save_tts(article, files={relative: source})
                        return True
        else:
            with self.books.locks.locked():
                book = self.books.load(ids['book_id'])
                chapter = next(c for c in book['chapters'] if c['id'] == ids['chapter_id'])
                if [b['text_ja'] for b in chapter['blocks'] if b.get('text_ja')] != paragraphs:
                    raise Conflict('章节原文已变化，请重试。')
                for metadata in [chapter.get('audio', {})] + chapter.get('audio_versions', []):
                    if not self._matches_audio(metadata, paragraphs, voice):
                        continue
                    try:
                        path = self.books.audio_asset(book['id'], metadata['path'])
                        self._validate_audio(path, metadata)
                    except (OSError, ValueError, LookupError, EOFError, wave.Error):
                        continue
                    metadata = dict(metadata, text_sha256=text_key(paragraphs), voice_sha256=voice['sha256'])
                    chapter.update(audio=metadata, voice_id=voice['id'], voice_mode='voice', voice_selected=True)
                    self.books.save(book, tts=True)
                    return True
        return False

    def _submit(self, target, paragraphs, voice, **ids):
        if not paragraphs or not any(p.strip() for p in paragraphs):
            raise ValueError('没有可朗读的日文正文。')
        if 'article_id' in ids:
            article = self.articles.load(ids['article_id'])
            segment_directory = self.articles.root / article['_directory'] / 'audio'
        else:
            book, chapter = self.books.chapter(ids['book_id'], ids['chapter_id'])
            occupied = {m.get('path') for c in book['chapters']
                        for m in [c.get('audio', {})] + c.get('audio_versions', []) if isinstance(m, dict)}
            book_stem = self._book_audio_stem(voice['name'], chapter.get('title'), ids['chapter_id'], occupied)
            segment_directory = self.books.folder(ids['book_id']) / 'audio'
        segment_voice_name = book_stem if 'book_id' in ids else voice['name']
        # Check finished recordings before consulting/loading the current model.
        # Legacy clients sending force=true still reuse valid same-voice audio.
        with self.queue.lock:
            active = self.queue.latest(target)
            if not (active and active['status'] in ACTIVE) and self._reuse_audio(paragraphs, voice, **ids):
                import time
                cached = dict(id=uuid.uuid4().hex, kind='tts', target=target, created_at=time.time_ns(),
                    status='completed', stage='complete', message='已复用保存的朗读。', percent=100, cached=True,
                    voice_id=voice['id'], completed=len(paragraphs), total=len(paragraphs), **ids)
                self.queue.tasks[cached['id']] = cached
                self.queue._save(cached)
                remove_segment_files(segment_directory, segment_voice_name)
                return {'status': 'ready'}
        key = cache_key(paragraphs, self.backend.identity(), voice)
        request = {'paragraphs': list(paragraphs), 'reference': str(self.voices.reference(voice)),
                   'voice': voice, 'seed': 42, 'cache_key': key,
                   'voice_name': segment_voice_name,
                   'reuse_segments': True,
                   'segment_directory': str(segment_directory)}
        task = self.queue.submit(target, request, key, voice_id=voice['id'], **ids)
        return {'task_id': task['id'], 'status': task['status']}

    def cancel_target(self, target):
        task = self.queue.latest(target) if self.queue else None
        return self.queue.cancel(task['id']) if task else {'status': 'idle'}

    def _commit(self, task, request, path, result):
        voice = request['voice']
        metadata = {'status': 'ready', 'segments': result['segments'], 'sample_rate': result['sample_rate'],
            'voice_id': voice['id'], 'voice_sha256': voice['sha256'], 'text_sha256': text_key(request['paragraphs']),
            'cache_key': task['cache_key'], 'task_id': task['id']}
        if 'article_id' in task:
            aid = task['article_id']
            with self.articles.locked():
                article = self.articles.load(aid)
                if article.get('status') != 'ready' or article['paragraphs'] != request['paragraphs']:
                    raise ValueError('文章原文已变化，请重新生成朗读。')
                relative = f"audio/{self._article_audio_filename(voice['name'], article['title'])}"
                destination = self.articles.root/article['_directory']/relative
                if destination.exists():
                    base = Path(relative)
                    relative = f"audio/{base.stem}-{task['cache_key'][:8]}{base.suffix}"
                    counter = 2
                    while (self.articles.root/article['_directory']/relative).exists():
                        relative = f"audio/{base.stem}-{task['cache_key'][:8]}-{counter}{base.suffix}"
                        counter += 1
                article.update(audio_path=relative, audio_status='ready', audio_segments=result['segments'],
                    audio_voice_mode='voice', audio_voice_id=voice['id'], audio_cache_key=task['cache_key'])
                self.articles.save_tts(article, files={relative: path})
                if self.examples and task.get('example_id'):
                    self.examples.save_audio(task['example_id'], voice['id'], self.articles.root / article['_directory'] / relative,
                                             dict(metadata, voice_name=voice['name']))
        else:
            relative = f"{request['voice_name']}.wav"
            book = self.books.load(task['book_id'])
            occupied = {m.get('path') for c in book['chapters']
                        for m in [c.get('audio', {})] + c.get('audio_versions', []) if isinstance(m, dict)}
            if relative in occupied or (self.books.folder(task['book_id'])/'audio'/relative).exists():
                relative = f"{request['voice_name']}-{task['cache_key'][:8]}.wav"
            metadata.update(path=relative, url=f"/api/books/{task['book_id']}/audio/{relative}")
            self.books.save_audio(task['book_id'], task['chapter_id'], request['paragraphs'], path, metadata)

    @staticmethod
    def _book_audio_stem(voice_name, chapter_title, chapter_id, occupied=()):
        def component(value):
            value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', str(value or ''))
            return re.sub(r'\s+', ' ', value).strip(' ._') or '未命名'
        voice, title = component(voice_name), component(chapter_title)
        base = f'{voice}_{title}'
        if len(base + '.wav') > 42:
            marker = hashlib.sha256(f'{voice}\0{title}'.encode('utf-8')).hexdigest()[:8]
            remaining = 42 - len(marker) - len('.wav') - 1
            voice_limit = min(len(voice), max(8, remaining // 2))
            title_limit = max(8, remaining - voice_limit - 1)
            base = f'{voice[:voice_limit]}_{title[:title_limit]}-{marker}'
        candidate = f'{base}.wav'
        if candidate not in set(occupied):
            return base
        marker = hashlib.sha256(f'{base}\0{chapter_id}'.encode('utf-8')).hexdigest()[:8]
        return f'{base[:max(8, 42 - len(marker) - len(".wav") - 1)]}-{marker}'

    @staticmethod
    def _article_audio_filename(voice_name, article_title):
        """Keep a readable filename while preserving Windows' path budget."""
        def component(value):
            value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', str(value or ''))
            value = re.sub(r'\s+', ' ', value).strip(' ._')
            return value or '未命名'
        voice, title = component(voice_name), component(article_title)
        filename = f'{voice}_{title}.wav'
        if len(filename) <= 42:
            return filename
        marker = hashlib.sha256(f'{voice}\0{title}'.encode('utf-8')).hexdigest()[:8]
        remaining = 42 - len(marker) - len('.wav') - 1
        voice_limit = min(len(voice), max(8, remaining // 2))
        title_limit = max(8, remaining - voice_limit)
        return f'{voice[:voice_limit]}_{title[:title_limit]}-{marker}.wav'

    def _routes(self):
        app = self.app

        @app.get('/api/tts/tasks')
        def tts_tasks():
            return jsonify(tasks=self.queue.list() if self.queue else [])

        @app.route('/api/tts/tasks/<tid>', methods=['GET', 'DELETE'])
        def tts_task(tid):
            self.require()
            return jsonify(self.queue.cancel(tid) if request.method == 'DELETE' else self.queue.get(tid))

        @app.get('/api/books/<int:bid>/audio/<path:filename>')
        def book_audio(bid, filename):
            path = self.books.audio_asset(bid, filename)
            return send_from_directory(path.parent, path.name, conditional=True)

        @app.route('/api/settings/voices/<int:vid>', methods=['PUT', 'DELETE'])
        @app.route('/api/settings/voices/<int:vid>/from-url', methods=['PUT'])
        @app.route('/api/settings/voices/from-url', methods=['POST'])
        def voice_edit(vid=None):
            return self.edit_voice(vid)

    def edit_voice(self, vid=None):
        self.require()
        with self.lock:
            if request.method == 'DELETE':
                mode = self.setting('voice-mode')
                referenced = mode.get('voice_id') == vid or any(s.get('voice_id') == vid for s in self.setting('news-sources'))
                referenced = referenced or any(t.get('voice_id') == vid and t['status'] in ACTIVE for t in self.queue.list())
                if not referenced:
                    for bid in self.books.ids():
                        b = self.books.load(bid, False)
                        if any(c.get('voice_id') == vid for c in b['chapters']):
                            referenced = True
                            break
                if referenced:
                    raise Conflict('此声线正在使用或被配置引用，请先切换声线。')
                self.voices.remove(vid)
                return jsonify(ok=True)
            payload = request.get_json(silent=True) or request.form
            blob = None
            upload = request.files.get('file')
            if upload:
                blob = upload.stream.read(20*1024*1024+1)
            elif payload.get('url'):
                blob, _ = self.download(payload['url'], max_bytes=20*1024*1024)
            voice = self.voices.save(payload.get('name'), blob, vid)
            if voice.get('previous_id') is not None:
                self._migrate_voice_ids({voice['previous_id']: voice['id']})
            return jsonify(id=voice['id'], name=voice['name'], duration=voice['duration'])

    def active_voice(self, payload):
        with self.lock:
            mode = self.setting('voice-mode')
            if payload.get('disabled'):
                mode.update(mode='none', voice_id=None)
            elif payload.get('voice_id'):
                self.require()
                self.voices.get(payload['voice_id'])
                mode.update(mode='voice', voice_id=int(payload['voice_id']))
            else:
                mode.update(mode='browser', voice_id=None)
            return self.setting('voice-mode', mode)

    def close(self):
        if self.queue:
            self.queue.close()
