"""Preview UI over the live local library; edits stay in preview memory."""
from copy import deepcopy
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlsplit, unquote
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
UPSTREAM = 'http://127.0.0.1:8428'
LOCK = threading.RLock()
SETTINGS, BOOKMARKS, PROGRESS, CHAPTER_VOICES = {}, {}, {}, {}

def upstream_json(path):
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(UPSTREAM + path, timeout=30)
        response.raise_for_status()
        return response.json()

def patch_book(book):
    result = deepcopy(book)
    bid = int(result.get('id', 0))
    if bid in PROGRESS:
        result['progress'] = deepcopy(PROGRESS[bid])
    for chapter in result.get('chapters', []):
        value = CHAPTER_VOICES.get((bid, int(chapter['id'])))
        if value:
            chapter.update(voice_mode=value['mode'], voice_id=value.get('voice_id'))
    return result

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def json_response(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        reference = re.fullmatch(r'/api/preview/voices/(\d+)/reference', path)
        if reference:
            return self.reference_audio(int(reference[1]))
        if path == '/app':
            document = (ROOT / 'static/index.html').read_text(encoding='utf-8')
            document = document.replace('</head>', '<link rel="stylesheet" href="/real-preview.css"></head>')
            document = document.replace('</body>', '<script src="/real-preview.js"></script></body>')
            data = document.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/preview-status':
            try:
                health = upstream_json('/api/health')
                return self.json_response({'status': health['status'], 'data': 'live-project-library', 'edits': 'preview-memory'})
            except requests.RequestException:
                return self.json_response({'detail': '请保持桌面端运行。'}, 502)
        if path.startswith('/api/'):
            return self.proxy()
        if path.startswith('/static/'):
            base = (ROOT / 'static').resolve()
            source = (base / unquote(path[len('/static/'):])).resolve()
            if not source.is_relative_to(base) or not source.is_file():
                return self.send_error(404)
            data = source.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', self.guess_type(str(source)))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def reference_audio(self, voice_id):
        from tts_service import VoiceStore
        try:
            selected = next((voice for voice in upstream_json('/api/settings/voices') if voice['id'] == voice_id), None)
            if selected is None or not (ROOT / 'data' / 'voices').is_dir():
                return self.json_response({'detail': '参照音声が見つかりません。'}, 404)
            store = VoiceStore(ROOT / 'data')
            voice = store.get(voice_id)
            if voice['name'] != selected['name']:
                return self.json_response({'detail': '参照音声が見つかりません。'}, 404)
            blob = store.reference(voice).read_bytes()
        except LookupError:
            return self.json_response({'detail': '参照音声が見つかりません。'}, 404)
        except (OSError, ValueError, requests.RequestException):
            return self.json_response({'detail': '参照音声を読み込めません。'}, 503)
        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Content-Length', str(len(blob)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(blob)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self): self.write_request()
    def do_PUT(self): self.write_request()
    def do_DELETE(self): self.write_request()

    def write_request(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get('Content-Length', '0'))
        if length > 1024 * 1024:
            return self.json_response({'detail': '预览请求过大。'}, 413)
        raw = self.rfile.read(length)
        if self.command == 'POST' and path in ('/api/browser-speech', '/api/desktop/edge-speech'):
            return self.proxy(raw)
        try:
            payload = json.loads(raw or '{}')
            with LOCK:
                match = re.fullmatch(r'/api/articles/(\d+)/bookmarks', path)
                if match and self.command in ('POST', 'DELETE'):
                    aid = int(match[1]); upstream_json(f'/api/articles/{aid}')
                    BOOKMARKS[aid] = self.command == 'POST'
                    return self.json_response({'ok': True, 'bookmarked': BOOKMARKS[aid], 'preview_only': True})
                match = re.fullmatch(r'/api/books/(\d+)/progress', path)
                if match and self.command == 'PUT':
                    bid = int(match[1]); book = upstream_json(f'/api/books/{bid}')
                    PROGRESS[bid] = {**book.get('progress', {}), **PROGRESS.get(bid, {}), **payload}
                    return self.json_response(patch_book(book))
                match = re.fullmatch(r'/api/books/(\d+)/chapters/(\d+)/voice', path)
                if match and self.command == 'PUT':
                    CHAPTER_VOICES[(int(match[1]), int(match[2]))] = payload
                    return self.json_response({'ok': True, 'preview_only': True})
                match = re.fullmatch(r'/api/settings/news-sources/(\d+)', path)
                if match and self.command == 'PUT':
                    minimum = payload.get('minimum_count')
                    if type(minimum) is not int or not 0 <= minimum <= 100:
                        return self.json_response({'detail': '最低記事数は0〜100の整数で入力してください。'}, 400)
                    sources = deepcopy(SETTINGS.get('news-sources') or upstream_json('/api/settings/news-sources'))
                    source = next((item for item in sources if item['id'] == int(match[1])), None)
                    if source is None:
                        return self.json_response({'detail': 'ニュースソースが見つかりません。'}, 404)
                    source['minimum_count'] = minimum
                    daily = SETTINGS.get('daily-content') or upstream_json('/api/settings/daily-content')
                    if sum(item.get('minimum_count', 0) for item in sources) > daily['target_count']:
                        return self.json_response({'detail': '最低記事数の合計は記事数を超えられません。'}, 400)
                    SETTINGS['news-sources'] = sources
                    return self.json_response(source)
                match = re.fullmatch(r'/api/settings/(library|voice-mode|browser-voice|active-voice|daily-content|daily-schedule)', path)
                if match and self.command == 'PUT':
                    key = match[1]
                    if key in ('browser-voice', 'active-voice'):
                        mode = deepcopy(SETTINGS.get('voice-mode') or upstream_json('/api/settings/voice-mode'))
                        if key == 'browser-voice':
                            mode.update(mode='browser', voice_id=None, browser_voice_name=payload['name'], browser_voice_label=payload.get('label', 'ブラウザー'))
                        elif payload.get('disabled'): mode.update(mode='disabled', voice_id=None)
                        elif payload.get('browser'): mode.update(mode='browser', voice_id=None)
                        else: mode.update(mode='voice', voice_id=payload.get('voice_id'))
                        SETTINGS['voice-mode'] = mode
                        return self.json_response(mode)
                    original = upstream_json('/api/settings/' + key)
                    updated = {**original, **SETTINGS.get(key, {}), **payload}
                    if key == 'daily-content':
                        target = updated.get('target_count')
                        if type(target) is not int or not 1 <= target <= 500:
                            return self.json_response({'detail': '記事数は1〜500の整数で入力してください。'}, 400)
                        sources = SETTINGS.get('news-sources') or upstream_json('/api/settings/news-sources')
                        required = sum(item.get('minimum_count', 0) for item in sources)
                        if target < required:
                            return self.json_response({'detail': f'記事数は最低合計の{required}篇以上にしてください。'}, 400)
                        updated.update(source_count=len(sources), required_count=required)
                    SETTINGS[key] = updated
                    return self.json_response(SETTINGS[key])
            return self.json_response({'detail': '界面预览不执行导入、生成、删除或文库维护。请在正式应用中执行。'}, 409)
        except (ValueError, KeyError):
            return self.json_response({'detail': '预览参数无效。'}, 400)
        except requests.RequestException:
            return self.json_response({'detail': '当前文库服务不可用，请保持桌面端运行。'}, 502)

    def patch_json(self, path, value):
        with LOCK:
            setting = re.fullmatch(r'/api/settings/([^/]+)', path)
            if setting and setting[1] in SETTINGS: value = deepcopy(SETTINGS[setting[1]])
            if path == '/api/settings/daily-content' and 'news-sources' in SETTINGS:
                value.update(source_count=len(SETTINGS['news-sources']), required_count=sum(source.get('minimum_count', 0) for source in SETTINGS['news-sources']))
            if setting and setting[1] in SETTINGS: return value
            if path == '/api/settings/voices' and isinstance(value, list) and SETTINGS.get('voice-mode'):
                mode = SETTINGS['voice-mode']
                for voice in value: voice['active'] = mode.get('mode') == 'voice' and voice['id'] == mode.get('voice_id')
            if path == '/api/bookmarks':
                values = {int(item['id']): item for item in value}
                for aid, saved in BOOKMARKS.items():
                    if saved and aid not in values: values[aid] = {**upstream_json(f'/api/articles/{aid}'), 'bookmark_context': True}
                    if not saved: values.pop(aid, None)
                value = list(values.values())
            articles = value.get('articles', []) if isinstance(value, dict) else value if path == '/api/bookmarks' else []
            for article in articles:
                if int(article['id']) in BOOKMARKS: article['bookmarked'] = BOOKMARKS[int(article['id'])]
            if re.fullmatch(r'/api/(?:articles|bookmarks)/\d+', path) and int(value.get('id', 0)) in BOOKMARKS:
                value['bookmarked'] = BOOKMARKS[int(value['id'])]
            if path == '/api/books': value['books'] = [patch_book(book) for book in value.get('books', [])]
            if re.fullmatch(r'/api/books/\d+', path): value = patch_book(value)
            if re.fullmatch(r'/api/books/\d+/chapters/\d+', path):
                value['book'] = patch_book(value['book'])
                voice = CHAPTER_VOICES.get((int(value['book']['id']), int(value['chapter']['id'])))
                if voice: value['chapter'].update(voice_mode=voice['mode'], voice_id=voice.get('voice_id'))
            return value

    def proxy(self, raw=None):
        path = urlsplit(self.path).path
        try:
            headers = {'Accept-Encoding': 'identity'}
            for key in ('Range', 'If-None-Match', 'If-Modified-Since', 'Content-Type'):
                if self.headers.get(key): headers[key] = self.headers[key]
            with requests.Session() as session:
                session.trust_env = False
                with session.request(self.command, UPSTREAM + self.path, data=raw, headers=headers,
                                     stream=True, allow_redirects=False, timeout=(5, 180)) as response:
                    content_type = response.headers.get('Content-Type', '')
                    if 'application/json' in content_type and response.ok:
                        return self.json_response(self.patch_json(path, response.json()), response.status_code)
                    self.send_response(response.status_code)
                    for key in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges', 'ETag', 'Last-Modified'):
                        if key in response.headers: self.send_header(key, response.headers[key])
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    for chunk in response.iter_content(128 * 1024): self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        except requests.RequestException:
            self.json_response({'detail': '真实文库服务连接失败，请保持桌面端运行。'}, 502)

if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 8499), Handler)
    print('真实文库界面预览：http://127.0.0.1:8499/demo.html', flush=True)
    try: server.serve_forever()
    finally: server.server_close()
