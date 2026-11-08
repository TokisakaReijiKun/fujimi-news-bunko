"""Paired-device access to the existing PC speech controller and its queue."""
from __future__ import annotations

import threading
import unicodedata

from werkzeug.exceptions import ServiceUnavailable

from browser_tts import browser_voice
from library_sync import LibrarySyncError
from tts_service import ACTIVE


class DeviceSpeechError(Exception):
    def __init__(self, detail, status=400, code='invalid_request'):
        super().__init__(detail)
        self.detail, self.status, self.code = detail, status, code


class DeviceSpeech:
    def __init__(self, library, controller):
        self.library, self.controller = library, controller
        self.lock = threading.RLock()
        # Ownership belongs to a pairing session, not a caller-supplied device ID.
        self.tasks = {}

    def capabilities(self):
        return {'speech_available': self.controller is not None,
                'speech_model_available': bool(self.controller is not None and self.controller.enabled)}

    def entity(self, payload):
        if not isinstance(payload, dict):
            raise DeviceSpeechError('朗读请求格式不正确。')
        key = payload.get('key')
        if not isinstance(key, str) or not key or len(key) > 500:
            raise DeviceSpeechError('请选择需朗读的同步文章或书籍。')
        if payload.get('mode') not in ('voice', 'browser'):
            raise DeviceSpeechError('请选择参考声线或本地浏览器声线。')
        if self.library is None or self.controller is None:
            raise DeviceSpeechError('PC 远程朗读服务未启用。', 503, 'speech_unavailable')
        try:
            kind, identifier, _ = self.library._entity_for_key(key)
        except (LibrarySyncError, LookupError, FileNotFoundError):
            raise DeviceSpeechError('PC 文库中没有此项目，请先补传内容。', 404, 'entity_missing') from None
        if kind not in ('article', 'book'):
            raise DeviceSpeechError('此同步项目不能生成朗读。')
        cid = payload.get('chapter_id')
        if kind == 'book' and (type(cid) is not int or cid < 1):
            raise DeviceSpeechError('请选择有效的书籍章节。')
        if kind == 'article' and cid is not None:
            raise DeviceSpeechError('文章朗读不接受章节编号。')
        return kind, identifier, cid

    def _voice_payload(self, payload):
        controller = self.controller
        if payload['mode'] == 'voice':
            name = payload.get('voice_name')
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise DeviceSpeechError('请选择有效的参考声线名称。')
            name = unicodedata.normalize('NFC', name.strip())
            try:
                controller.require()
                voice = next((item for item in controller.voices.list() if item['name'] == name), None)
            except (ServiceUnavailable, OSError, ValueError, RuntimeError, ImportError):
                raise DeviceSpeechError('PC Irodori 服务或参考声线不可用，请在 PC 检查模型和声线文件。',
                                        503, 'speech_unavailable') from None
            if voice is None:
                raise DeviceSpeechError('PC 没有此参考声线，请先补传声线。', 404, 'voice_missing')
            return {'mode': 'voice', 'voice_id': voice['id']}
        name = payload.get('browser_voice_name')
        if not isinstance(name, str) or len(name) > 100:
            raise DeviceSpeechError('请选择有效的本地浏览器声线。')
        try:
            browser_voice(name)
        except ValueError:
            raise DeviceSpeechError('PC 不支持此本地浏览器声线。', 404, 'voice_missing') from None
        backend = controller.app.extensions.get('browser_tts')
        try:
            voice = next((item for item in backend.voices() if item['id'] == name), None) if backend else None
        except (OSError, ValueError, RuntimeError, ImportError):
            voice = None
        if not voice or not voice.get('available', True):
            raise DeviceSpeechError('PC 上所选浏览器声线的模型或依赖不可用。', 503, 'speech_unavailable')
        return {'mode': 'browser', 'browser_voice_name': name}

    def start(self, payload, entity, owner, authorize):
        controller = self.controller
        kind, identifier, cid = entity
        target = f'article:{identifier}' if kind == 'article' else f'book:{identifier}:{cid}'
        with controller.lock:
            authorize()
            voice_payload = self._voice_payload(payload)
            latest = controller.queue.latest(target) if controller.queue else None
            if latest and latest['status'] in ACTIVE:
                with self.lock:
                    owned = self.tasks.get(latest['id'])
                if not owned or owned['owner'] != owner:
                    raise DeviceSpeechError('此项目已有其他朗读任务，请等待完成后重试。', 409, 'speech_busy')
            try:
                result = (controller.submit_article(identifier, voice_payload) if kind == 'article'
                          else controller.submit_chapter(identifier, cid, voice_payload))
            except LookupError:
                raise DeviceSpeechError('PC 上的文章或章节不存在，请先补传内容。', 404, 'entity_missing') from None
            except (ServiceUnavailable, OSError, RuntimeError, ImportError):
                raise DeviceSpeechError('PC 朗读模型或依赖不可用，请在 PC 检查朗读服务。',
                                        503, 'speech_unavailable') from None
            response = {'status': result['status'], 'key': payload['key']}
            if result.get('task_id'):
                tid = result['task_id']
                with self.lock:
                    self.tasks[tid] = {'owner': owner, 'key': payload['key']}
                response['task_id'] = tid
            if 'cached' in result:
                response['cached'] = bool(result['cached'])
            elif result['status'] == 'ready' and payload['mode'] == 'voice':
                response['cached'] = True
            return response

    def task(self, tid, owner, cancel=False):
        with self.lock:
            owned = self.tasks.get(tid)
        if not owned or owned['owner'] != owner:
            raise DeviceSpeechError('远程朗读任务不存在。', 404, 'task_missing')
        queue = self.controller.queue if self.controller is not None else None
        if queue is None:
            raise DeviceSpeechError('PC 朗读服务未启用。', 503, 'speech_unavailable')
        try:
            task = queue.cancel(tid) if cancel else queue.get(tid)
        except LookupError:
            raise DeviceSpeechError('远程朗读任务不存在。', 404, 'task_missing') from None
        message = str(task.get('message') or '')
        # Failed synthesis can contain dependency diagnostics; keep those on the PC.
        if task['status'] == 'failed':
            message = 'PC 朗读生成失败，请在 PC 检查模型与声线后重试。'
        return {'status': task['status'], 'task_id': tid,
                'completed': task.get('completed', 0), 'total': task.get('total', 0),
                'message': message, 'key': owned['key']}
