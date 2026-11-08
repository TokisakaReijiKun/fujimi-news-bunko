"""Compare the real mobile text form with Demo 2.46, using isolated API fixtures."""
import asyncio
import aiohttp
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "tests/mobile-japanese-design"
sys.path.insert(0, str(DEMO))
from render_designs import EDGE, HeadlessRenderer

OUT = ROOT / "build/qa/mobile-app-1.1.5"
NATIVE = """if(location.pathname==='/app')window.FujimiMobile={
request(raw,id){const req=JSON.parse(raw);fetch(req.path,{method:req.method,body:req.body,headers:{'Content-Type':'application/json'}}).then(async r=>window.__fujimiMobileResolve(id,r.status,await r.text()));},
mobileStatus(){return JSON.stringify({paired:false,deepseek_configured:false,allow_cellular:false,exact_alarm:true});}
};window.__layoutErrors=[];addEventListener('error',e=>__layoutErrors.push(e.message));addEventListener('unhandledrejection',e=>__layoutErrors.push(String(e.reason?.message||e.reason)));"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        route = unquote(urlsplit(self.path).path)
        if route.startswith('/api/'):
            values = {
                '/api/health': {'status': 'ok', 'runtime': 'android', 'tts': 'browser'},
                '/api/days': [], '/api/bookmarks': [], '/api/examples': [],
                '/api/settings/voice-mode': {'mode': 'browser', 'browser_voice_name': 'ja-JP-KeitaNeural'},
                '/api/settings/voices': [],
                '/api/browser-voices': [{'id': 'ja-JP-KeitaNeural', 'name': '圭太', 'available': True}],
                '/api/settings/library': {'sort': 'recent', 'lookup_chinese_translations': True},
                '/api/settings/daily-content': {'target_count': 10},
                '/api/settings/daily-schedule': {'mode': 'manual', 'time': '00:00'},
                '/api/dictionary/stats': {'entries': 159396, 'dictionary': '日中辞典'},
                '/api/books': {'books': [{'id': 9001, 'title': '検証用書籍', 'author': '検証', 'cover_url': ''}]},
                '/api/settings/news-sources': [],
            }
            return self.reply(json.dumps(values.get(route, []), ensure_ascii=False).encode(), 'application/json')
        if route in ('/app', '/pc'):
            file = ROOT / 'static/index.html'
        elif route == '/demo':
            file = DEMO / 'native-app.html'
        elif route.startswith('/static/'):
            file = (ROOT / 'static' / route.removeprefix('/static/')).resolve()
            if not file.is_relative_to(ROOT / 'static'):
                return self.send_error(404)
        elif route.removeprefix('/') in ('next-ui.js', 'next-ui.css', 'native-reader.css', 'epub-reader.css'):
            file = DEMO / route.removeprefix('/')
        else:
            return self.send_error(404)
        if not file.is_file():
            return self.send_error(404)
        self.reply(file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')

    def do_POST(self):
        self.reply(b'{"detail":"Isolated layout fixture does not save content."}', 'application/json', 501)

    def reply(self, content, kind, status=200):
        self.send_response(status)
        self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/') else ''))
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)


async def until(browser, expression):
    for _ in range(200):
        if await browser.evaluate(expression):
            return
        await asyncio.sleep(.05)
    state = await browser.evaluate("({path:location.pathname,open:document.querySelector('#web-text-dialog')?.open,options:document.querySelector('#web-text-voice')?.innerHTML,errors:window.__layoutErrors})")
    raise AssertionError('Layout did not settle: ' + expression + ' ' + json.dumps(state, ensure_ascii=False))


MEASURE = """(()=>{
const d=document.querySelector('#web-text-dialog'),q=s=>d.querySelector(s);
const measure=e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();return {width:r.width,height:r.height,font:c.font,lineHeight:c.lineHeight,color:c.color,background:c.backgroundColor,padding:c.padding,border:c.border,borderRadius:c.borderRadius,shadow:c.boxShadow,gap:c.gap,columns:c.gridTemplateColumns};};
return {dialog:measure(d),form:measure(q('form')),heading:measure(q('header')),title:measure(q('h3')),kicker:measure(q('.section-kicker')),close:measure(q('.icon-button')),label:measure(q('.web-text-fields label')),input:measure(q('[name=title]')),textarea:measure(q('textarea')),note:measure(q('.web-runtime-note')),actions:measure(q('.web-form-actions')),cancel:measure(q('#cancel-web-text-dialog')),examples:measure(q('#web-example-trigger')),voice:measure(q('.android-select-trigger')||q('#web-text-voice')),submit:measure(q('[type=submit]')),copy:[q('.section-kicker').textContent,q('h3').textContent,...q('.web-text-fields').querySelectorAll('label>span')].map(x=>typeof x==='string'?x:x.textContent),bodyCopy:d.textContent.trim(),errors:window.__layoutErrors,overflow:d.scrollWidth>d.clientWidth+1,screenOverflow:document.documentElement.scrollWidth>innerWidth};})()"""


async def inspect(browser, url, variant, width):
    await browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 844, 'deviceScaleFactor': 1, 'mobile': width < 600})
    await browser.call('Page.navigate', {'url': url + '/' + variant})
    ready = "window.__fujimiApp?.ready" if variant == 'app' else "window.__newPreview?.ready" if variant == 'demo' else "document.readyState==='complete'&&typeof showView==='function'"
    await until(browser, ready)
    if variant == 'app':
        await browser.evaluate("window.__fujimiNavigate('library')")
        labels = await browser.evaluate("window.__fujimiAppRoot.querySelectorAll('.library-page .section-label').length")
        await browser.evaluate("window.__fujimiNavigate('reader')")
        await browser.evaluate("window.__fujimiAppRoot.querySelector('.paste-action').click()")
    elif variant == 'demo':
        labels = None
        await browser.evaluate("window.__redesignNavigate('reader')")
        await browser.evaluate("window.__redesignRoot.querySelector('.paste-action').click()")
    else:
        labels = None
        await browser.evaluate("document.querySelector('#open-web-text-dialog').click()")
    await until(browser, "document.querySelector('#web-text-dialog').open&&document.querySelector('#web-text-voice').value")
    await browser.evaluate("(async()=>{await document.fonts.ready;await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)})()")
    metrics = await browser.evaluate(MEASURE)
    metrics['shelfLabels'] = labels
    data = await browser.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
    (OUT / f'text-{variant}-{width}.png').write_bytes(base64.b64decode(data['data']))
    if variant == 'app':
        await browser.evaluate("document.querySelector('#web-text-dialog .android-select-trigger').click()")
        assert await browser.evaluate("document.querySelector('#web-text-dialog .android-select-trigger').getAttribute('aria-expanded')==='true'")
        await browser.evaluate("document.querySelector('#web-text-dialog .android-select-option[aria-selected=true]').click()")
        assert await browser.evaluate("document.querySelector('#web-text-dialog .android-select-trigger').getAttribute('aria-expanded')==='false'")
    await browser.evaluate("document.querySelector('#web-text-dialog [name=title]').value='検証';document.querySelector('#web-text-dialog textarea').value='検証用本文。'")
    await browser.evaluate("document.querySelector('#cancel-web-text-dialog').click()")
    assert not await browser.evaluate("document.querySelector('#web-text-dialog').open")
    assert not metrics['overflow'] and not metrics['screenOverflow'] and not metrics['errors'], metrics
    return metrics


async def run():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='fujimi-text-layout-', ignore_cleanup_errors=True) as temporary:
            profile = Path(temporary) / 'edge'
            process = subprocess.Popen([str(EDGE), '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + str(profile), 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for _ in range(150):
                    if (profile / 'DevToolsActivePort').exists():
                        break
                    await asyncio.sleep(.1)
                port, endpoint = (profile / 'DevToolsActivePort').read_text().splitlines()[:2]
                async with aiohttp.ClientSession() as client:
                    async with client.ws_connect(f'http://127.0.0.1:{port}{endpoint}', max_msg_size=32*1024*1024) as socket:
                        browser = HeadlessRenderer(socket)
                        target = await browser.call('Target.createTarget', {'url': 'about:blank'}, browser=True)
                        browser.session = (await browser.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True}, browser=True))['sessionId']
                        await browser.call('Page.enable')
                        await browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': NATIVE})
                        results = {}
                        for width in (375, 390):
                            results[str(width)] = {variant: await inspect(browser, f'http://127.0.0.1:{server.server_port}', variant, width) for variant in ('demo', 'app')}
                            reference = results[str(width)]['demo']
                            actual = results[str(width)]['app']
                            assert actual['shelfLabels'] == 0
                            assert actual['copy'] == reference['copy']
                            assert abs(actual['dialog']['height'] - reference['dialog']['height']) < 1
                            for component in ('heading', 'title', 'kicker', 'close', 'label', 'input', 'textarea', 'cancel', 'examples', 'submit'):
                                assert actual[component] == reference[component], (width, component, actual[component], reference[component])
                            for property in ('font', 'color', 'background', 'padding', 'border', 'borderRadius'):
                                assert actual['voice'][property] == reference['voice'][property], (width, property)
                        results['1440'] = {'pc': await inspect(browser, f'http://127.0.0.1:{server.server_port}', 'pc', 1440)}
                        (OUT / 'text-layout.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
                        print(json.dumps({width: {variant: {'height': value['dialog']['height'], 'copy': value['copy'], 'shelfLabels': value['shelfLabels']} for variant, value in variants.items()} for width, variants in results.items()}, ensure_ascii=False), flush=True)
                        await browser.call('Browser.close', browser=True)
                process.wait(timeout=15)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    asyncio.run(run())
