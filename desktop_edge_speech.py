"""Bounded Edge online speech endpoint for the Windows desktop host."""
from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path
import re
import tempfile

from flask import jsonify, request, send_file


VOICES = {'ja-JP-KeitaNeural', 'ja-JP-NanamiNeural'}
MAX_TEXT = 4000
MAX_AUDIO = 8 * 1024 * 1024


def synthesize(text, voice):
    import edge_tts

    async def collect():
        data = bytearray()
        async for chunk in edge_tts.Communicate(text, voice, connect_timeout=10, receive_timeout=45).stream():
            if chunk['type'] == 'audio':
                data.extend(chunk['data'])
                if len(data) > MAX_AUDIO:
                    raise ValueError('朗读音频超过大小限制。')
        if not data:
            raise ValueError('在线声线未返回音频。')
        return bytes(data)

    return asyncio.run(collect())


def _paragraph_segments(paragraphs, boundaries):
    normalized = [re.sub(r'\s+', '', paragraph) for paragraph in paragraphs]
    if not normalized or not all(normalized) or not boundaries:
        raise ValueError('在线声线未返回完整的段落时间。')
    starts = [None] * len(normalized)
    paragraph_index = 0
    cursor = 0
    for boundary in boundaries:
        sentence = re.sub(r'\s+', '', boundary.get('text', ''))
        if not sentence:
            raise ValueError('在线声线未返回完整的段落时间。')
        match = normalized[paragraph_index].find(sentence, cursor)
        if match < 0:
            paragraph_index += 1
            cursor = 0
            if paragraph_index >= len(normalized):
                raise ValueError('在线声线逐句时间与正文不一致。')
            match = normalized[paragraph_index].find(sentence)
            if match < 0:
                raise ValueError('在线声线逐句时间与正文不一致。')
        if starts[paragraph_index] is None:
            starts[paragraph_index] = int(boundary['offset']) / 10_000_000
        cursor = match + len(sentence)
    if any(start is None for start in starts):
        raise ValueError('在线声线未返回完整的段落时间。')
    total = max((int(item['offset']) + int(item['duration']) for item in boundaries)) / 10_000_000
    edges = [0, *starts[1:], total]
    if any(end <= start for start, end in zip(edges, edges[1:])):
        raise ValueError('在线声线段落时间无效。')
    return [{'duration': end - start, 'speech_start_offset': max(0, starts[index] - start),
             'timing_source': 'edge_sentence'}
            for index, (start, end) in enumerate(zip(edges, edges[1:]))]


def synthesize_with_segments(text, voice, paragraphs):
    import edge_tts

    async def collect():
        data = bytearray()
        boundaries = []
        async for chunk in edge_tts.Communicate(text, voice, connect_timeout=10, receive_timeout=60).stream():
            if chunk['type'] == 'audio':
                data.extend(chunk['data'])
                if len(data) > MAX_AUDIO:
                    raise ValueError('朗读音频超过大小限制。')
            elif chunk['type'] == 'SentenceBoundary':
                boundaries.append(chunk)
        if not data:
            raise ValueError('在线声线未返回音频。')
        return bytes(data), _paragraph_segments(paragraphs, boundaries)

    return asyncio.run(collect())


def _edge_filename(title, voice):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', f'{voice}_{title}')
    value = re.sub(r'\s+', ' ', value).strip(' ._') or 'edge-tts'
    return f'{value[:92]}.mp3'


def register_edge_speech(app):
    @app.post('/api/desktop/edge-speech')
    def edge_speech():
        body = request.get_json(silent=True) or {}
        text, voice = body.get('text'), body.get('voice')
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or voice not in VOICES:
            return jsonify(detail='请选择可用的日语在线声线，正文须为 1–4000 字。'), 400
        try:
            audio = synthesize(text, voice)
        except Exception:
            app.logger.exception('Desktop online speech failed')
            return jsonify(detail='在线声线暂不可用，请检查网络后重试。'), 502
        return send_file(io.BytesIO(audio), mimetype='audio/mpeg', download_name='speech.mp3')

    @app.post('/api/articles/<int:aid>/edge-tts')
    def edge_article_tts(aid):
        body = request.get_json(silent=True) or {}
        voice = body.get('voice')
        if voice not in VOICES:
            return jsonify(detail='请选择圭太或七海在线声线。'), 400
        store = app.article_store
        article = store.load(aid)
        if article.get('status') != 'ready':
            return jsonify(detail='正文不可用，不能生成朗读。'), 409
        try:
            label = '圭太' if voice.endswith('KeitaNeural') else '七海'
            filename = _edge_filename(article['title'], label)
            folder = store.root / article['_directory']
            segments = article.get('audio_segments', [])
            precise = (len(segments) == len(article['paragraphs'])
                       and all(isinstance(segment, dict) and segment.get('timing_source') == 'edge_sentence'
                               for segment in segments))
            relative = article.get('audio_path', '')
            if precise and article.get('audio_voice_name') == voice and relative.startswith('audio/'):
                try:
                    store.asset(aid, relative)
                except LookupError:
                    pass
                else:
                    return jsonify(status='ready', cached=True, article=app.extensions['tts'].article_wire(article))
            audio, segments = synthesize_with_segments('\n'.join(article['paragraphs']), voice, article['paragraphs'])
            relative = f'audio/{filename}'
            if (folder / relative).exists():
                stem = f'{Path(filename).stem}-{hashlib.sha256(voice.encode()).hexdigest()[:8]}'
                relative = f'audio/{stem}.mp3'
                number = 2
                while (folder / relative).exists():
                    relative = f'audio/{stem}-{number}.mp3'
                    number += 1
            with tempfile.NamedTemporaryFile(prefix='fujimi-edge-', suffix='.mp3', delete=False) as temporary:
                temporary.write(audio)
                source = Path(temporary.name)
            try:
                article.update(audio_path=relative, audio_segments=segments, audio_status='ready',
                               audio_voice_mode='browser', audio_voice_id=None, audio_voice_name=voice)
                saved = store.save_tts(article, files={relative: source})
            finally:
                source.unlink(missing_ok=True)
        except Exception:
            app.logger.exception('Desktop article online speech failed')
            return jsonify(detail='在线声线生成或保存失败，请检查网络后重试。'), 502
        return jsonify(status='ready', article=app.extensions['tts'].article_wire(saved))
