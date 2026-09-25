"""Temporary-data browser check: select 缓存検証 and 浅倉透, then 保存并阅读.

Run with Tokyo Python from the project root. The backend rejects any synthesis.
GET /qa/result exposes the observed import requests and synthesized-call count.
No personal data directory or external translation configuration is loaded.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import request
from server import make_local_server
from test_tts import TTSTests, wav_bytes
from tts_service import text_key


if __name__ == '__main__':
    fixture = TTSTests()
    fixture.setUp()
    app, tts, backend = fixture.app, fixture.tts, fixture.backend
    requests_seen = []
    voice = tts.voices.save('浅倉透', wav_bytes())
    examples = app.extensions['examples']
    item = examples.create('缓存検証', '今日は本を読みます。', translated_paragraphs=['今天读书。'])
    audio = fixture.data / 'cached.wav'
    audio.write_bytes(wav_bytes(.1))
    examples.save_audio(item['id'], voice['id'], audio, {
        'voice_name': voice['name'], 'voice_sha256': voice['sha256'],
        'text_sha256': text_key(['今日は本を読みます。']),
        'segments': [{'duration': .1, 'speech_start_offset': 0}], 'sample_rate': 48000,
    })

    def forbidden():
        raise AssertionError('Cached import must not consult or load the model')
    backend.identity = forbidden

    @app.after_request
    def record(response):
        if request.path == '/api/articles/text' and request.method == 'POST':
            body = response.get_json() or {}
            requests_seen.append(dict(payload=request.get_json(), status=response.status_code,
                                      article_id=body.get('id'), audio_status=body.get('audio_status'),
                                      translations=body.get('translated_paragraphs')))
        return response

    @app.get('/qa/result')
    def result():
        return dict(requests=requests_seen, synthesis_calls=len(backend.calls))

    http = make_local_server(app, '127.0.0.1', 8438)
    try:
        http.serve_forever()
    finally:
        http.server_close()
        fixture.tearDown()
