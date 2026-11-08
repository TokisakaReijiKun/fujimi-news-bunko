"""Isolated voice-sheet interaction and layout checks using staged APK assets."""
import asyncio
import base64
import json
import mimetypes
from pathlib import Path
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit
from zipfile import ZipFile

import aiohttp
import verify_mobile_text_layout as fixture

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/qa/voice-playback-fix'
ASSETS = Path('C:/Users/A1512/.gradle/fujimi-android-build/app/generated/assets/static')
BASE = ROOT / 'dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.25-release.apk'
with ZipFile(BASE) as package:
    BEFORE = {n.removeprefix('assets/static/'): package.read(n) for n in package.namelist() if n.startswith('assets/static/') and not n.endswith('/')}
AFTER = {name: (ASSETS / name).read_bytes() for name in BEFORE}


class Handler(fixture.Handler):
    phase = 'after'
    mode = {}
    catalog = []
    voices = []
    calls = []

    @classmethod
    def reset(cls):
        cls.mode = {'mode': 'voice', 'voice_id': 44, 'browser_voice_name': 'ja-JP-KeitaNeural', 'browser_voice_label': '圭太'}
        cls.catalog = [{'id': 'android:system', 'name': 'システム音声', 'available': True, 'read_only': True},
                       {'id': 'ja-JP-KeitaNeural', 'name': '圭太', 'available': True},
                       {'id': 'ja-JP-NanamiNeural', 'name': '七海', 'available': True},
                       {'id': 'kokoro:jf_alpha', 'name': 'アルファ', 'available': True, 'saved_audio_only': True},
                       {'id': 'voicevox:109', 'name': '東北イタコ', 'available': True, 'saved_audio_only': True},
                       {'id': 'voicevox:89', 'name': 'Voidoll', 'available': True, 'saved_audio_only': True}]
        cls.voices = [{'id': 44, 'name': '折木奉太郎', 'saved_audio_only': True}]
        cls.calls = []

    def api(self, method, route, body=None):
        cls = type(self)
        body = body or {}
        cls.calls.append({'method': method, 'path': route, 'body': body})
        value = None
        if route == '/api/settings/voice-mode':
            value = cls.mode
        elif route in ('/api/browser-voices', '/api/settings/voice-catalog'):
            value = [voice for voice in cls.catalog if route.endswith('voice-catalog') or not voice.get('hidden')]
        elif route == '/api/settings/browser-voice':
            cls.mode.update(mode='browser', browser_voice_name=body['name'], browser_voice_label=body['label'])
            value = cls.mode
        elif route == '/api/settings/active-voice':
            cls.mode.update(mode='voice', voice_id=body['voice_id'])
            value = cls.mode
        elif route == '/api/settings/voice-file':
            if body.get('audio_url', '').endswith('/invalid.wav'):
                return self.reply(b'{"detail":"Invalid WAV fixture"}', 'application/json', 400)
            value = {'file_token': 'url-wave' if body.get('audio_url') else 'selected-wave', 'filename': 'sample.wav', 'duration': 2} if method == 'POST' else {'ok': True}
        elif route == '/api/settings/browser-voices':
            voice = next(v for v in cls.catalog if v['id'] == body['id'])
            if body.get('file_token'):
                voice['hidden'] = True
                cls.voices.append({'id': 201, 'name': body['name'], 'saved_audio_only': True})
            elif method == 'DELETE':
                voice['hidden'] = True
            else:
                voice.update(name=body['name'], hidden=False)
            value = {'ok': True}
        elif route == '/api/settings/voices':
            if method == 'POST':
                cls.voices.append({'id': 202, 'name': body['name'], 'saved_audio_only': True})
                value = {'ok': True}
            else:
                value = cls.voices
        elif route.startswith('/api/settings/voices/'):
            voice_id = int(route.rsplit('/', 1)[1])
            if method == 'DELETE':
                cls.voices = [v for v in cls.voices if v['id'] != voice_id]
            else:
                next(v for v in cls.voices if v['id'] == voice_id)['name'] = body['name']
            value = {'ok': True}
        elif route == '/api/dictionary/words/1':
            value = {'id': '1', 'spell': '成功', 'pron': 'せいこう', 'definitions': [], 'examples': []}
        else:
            return False
        self.reply(json.dumps(value, ensure_ascii=False).encode(), 'application/json')
        return True

    def do_GET(self):
        route = urlsplit(self.path).path
        if route.startswith('/api/') and self.api('GET', route):
            return
        name = 'index.html' if route in ('/app', '/pc') else route.removeprefix('/static/') if route.startswith('/static/') else None
        files = BEFORE if self.phase == 'before' else AFTER
        if name in files:
            return self.reply(files[name], mimetypes.guess_type(name)[0] or 'application/octet-stream')
        return super().do_GET()

    def do_POST(self):
        route = urlsplit(self.path).path
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or '{}')
        if not self.api(self.command, route, body):
            return self.reply(b'{"detail":"Unsupported fixture mutation"}', 'application/json', 501)

    do_PUT = do_POST
    do_DELETE = do_POST


NATIVE = fixture.NATIVE + """
window.confirm=()=>true;window.__voiceSpeechCalls=[];window.__voiceReferenceCalls=[];
if(window.FujimiMobile){
  FujimiMobile.speak=()=>{};FujimiMobile.stopSpeaking=()=>{};
  FujimiMobile.speakWithVoice=(text,rate,id,voice)=>{__voiceSpeechCalls.push({text,voice});queueMicrotask(()=>__fujimiTtsEvent(id,'start'));setTimeout(()=>__fujimiTtsEvent(id,'done'),30);};
}
HTMLMediaElement.prototype.play=function(){__voiceReferenceCalls.push(this.getAttribute('src'));return Promise.resolve();};
"""
Q = "window.__fujimiAppRoot.querySelector"


async def click(browser, selector):
    point = await browser.evaluate(f"(()=>{{const e={Q}({json.dumps(selector)});e.scrollIntoView({{block:'nearest'}});const r=e.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()")
    await browser.call('Input.dispatchMouseEvent', dict(type='mousePressed', button='left', clickCount=1, **point))
    await browser.call('Input.dispatchMouseEvent', dict(type='mouseReleased', button='left', clickCount=1, **point))


async def wait(browser, selector):
    try:
        open_dialog = '' if selector == '.settings-voice-select' else f"{Q}('dialog').open&&"
        await fixture.until(browser, f'{open_dialog}!!{Q}({json.dumps(selector)})')
    except AssertionError:
        await screenshot(browser, 'failed-interaction.png')
        print(await browser.evaluate("({sheet:window.__fujimiAppRoot.querySelector('dialog')?.textContent,toast:window.__fujimiAppRoot.querySelector('.toast')?.textContent,errors:window.__layoutErrors})"), flush=True)
        print(json.dumps(Handler.calls[-8:], ensure_ascii=False), flush=True)
        raise


async def screenshot(browser, name):
    result = await browser.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
    (OUT / name).write_bytes(base64.b64decode(result['data']))


async def inspect(browser, base_url, width, phase):
    Handler.reset(); Handler.phase = phase
    await browser.call('Network.clearBrowserCache')
    await browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
    await browser.call('Page.navigate', {'url': base_url + '/app'})
    await fixture.until(browser, "window.__fujimiApp?.ready&&!!window.__fujimiAppRoot.querySelector('link').sheet")
    await browser.evaluate("window.__fujimiNavigate('settings')")
    await wait(browser, '.settings-voice-select')
    await click(browser, '.settings-voice-select')
    await wait(browser, '.voice-manager-row')
    await browser.evaluate('(async()=>{await document.fonts.ready;await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)})()')
    metrics = await browser.evaluate("""(()=>{const root=window.__fujimiAppRoot,d=root.querySelector('dialog');return {heights:[...d.querySelectorAll('.voice-manager-row')].map(r=>r.getBoundingClientRect().height),overflow:d.scrollWidth>d.clientWidth+1||document.documentElement.scrollWidth>innerWidth,errors:window.__layoutErrors}})()""")
    await screenshot(browser, f'voices-{phase}-{width}.png')
    assert not metrics['overflow'] and not metrics['errors'], metrics
    if phase == 'before':
        return metrics
    assert max(metrics['heights']) <= 65, metrics
    main_label = Q + "('[data-voice-id=\"browser\"] .choice strong')"
    assert await browser.evaluate(main_label + ".textContent==='システム音声（圭太）'")
    assert await browser.evaluate("!window.__fujimiAppRoot.querySelector('[data-voice-id=\"browser\"] .choice small')")
    await click(browser, '[data-voice-id="browser"] .voice-more'); await wait(browser, '.voice-catalog-list')
    ids = await browser.evaluate("[...window.__fujimiAppRoot.querySelectorAll('.voice-catalog-list .voice-manager-row')].map(r=>r.dataset.voiceId)")
    assert ids == ['ja-JP-KeitaNeural', 'ja-JP-NanamiNeural', 'kokoro:jf_alpha', 'voicevox:109', 'voicevox:89'], ids
    assert await browser.evaluate("window.__fujimiAppRoot.querySelectorAll('.voice-catalog-list .voice-preview').length===5")
    assert await browser.evaluate("!window.__fujimiAppRoot.querySelector('.voice-catalog-list .voice-more')")
    assert await browser.evaluate("window.__fujimiAppRoot.querySelector('[data-voice-id=\"ja-JP-KeitaNeural\"] .choice').getAttribute('aria-pressed')==='true'")
    assert Handler.mode['mode']=='voice' and Handler.mode['voice_id']==44
    await screenshot(browser, f'voice-browser-options-{width}.png')
    assert await browser.evaluate('window.__fujimiHandleBack()')
    await wait(browser, '.voice-main-list')
    await click(browser, '[data-voice-id="browser"] .voice-more'); await wait(browser, '.voice-catalog-list')
    await browser.call('Input.dispatchKeyEvent', {'type': 'rawKeyDown', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27})
    await browser.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27})
    await wait(browser, '.voice-main-list')
    await click(browser, '[data-voice-id="browser"] .voice-more'); await wait(browser, '.voice-catalog-list')
    await click(browser, '[data-voice-id="ja-JP-NanamiNeural"] .voice-preview')
    await fixture.until(browser, "window.__voiceSpeechCalls.length===1")
    assert await browser.evaluate("__voiceSpeechCalls[0].voice==='ja-JP-NanamiNeural'")
    assert Handler.mode['mode']=='voice' and Handler.mode['voice_id']==44
    await click(browser, 'dialog .sheet-head button[aria-label="閉じる"]')
    await browser.evaluate("window.__fujimiNavigate('dictionary')")
    await browser.evaluate("loadDictionaryDetail(1,{reveal:true})")
    await fixture.until(browser, "!!document.querySelector('.dictionary-word-header .dictionary-speech-button')")
    await browser.evaluate("document.querySelector('.dictionary-word-header .dictionary-speech-button').click()")
    await fixture.until(browser, "window.__voiceSpeechCalls.some(c=>c.text==='せいこう'&&c.voice==='ja-JP-KeitaNeural')")
    assert Handler.mode['mode']=='voice' and Handler.mode['voice_id']==44
    await browser.evaluate("window.__fujimiNavigate('settings')")
    await wait(browser, '.settings-voice-select'); await click(browser, '.settings-voice-select')
    await wait(browser, '.voice-main-list')
    await click(browser, '[data-voice-id="browser"] .voice-more'); await wait(browser, '.voice-catalog-list')
    await click(browser, '[data-voice-id="voicevox:89"] .choice')
    await fixture.until(browser, f"!{Q}('dialog').open")
    await click(browser, '.settings-voice-select'); await wait(browser, '.voice-main-list')
    assert await browser.evaluate(main_label + ".textContent==='システム音声（Voidoll）'")
    assert await browser.evaluate(main_label + ".getBoundingClientRect().height<30")
    await screenshot(browser, f'voice-voidoll-{width}.png')
    await click(browser, '[data-voice-id="44"] .voice-preview')
    assert await browser.evaluate("__voiceReferenceCalls.includes('/api/settings/voices/44/reference')")
    await click(browser, '[data-voice-id="browser"] .voice-more'); await wait(browser, '.voice-catalog-list')
    await click(browser, '[data-voice-id="ja-JP-KeitaNeural"] .choice')
    await fixture.until(browser, f"!{Q}('dialog').open")
    assert Handler.mode['browser_voice_name'] == 'ja-JP-KeitaNeural'
    await browser.evaluate("window.__fujimiNavigate('dictionary')")
    await browser.evaluate("loadDictionaryDetail(1,{reveal:true})")
    await fixture.until(browser, "!!document.querySelector('.dictionary-word-header .dictionary-speech-button')")
    await browser.evaluate("document.querySelector('.dictionary-word-header .dictionary-speech-button').click()")
    await fixture.until(browser, "window.__voiceSpeechCalls.some(c=>c.text==='せいこう')")
    await browser.evaluate("window.__fujimiNavigate('settings')")
    await wait(browser, '.settings-voice-select'); await click(browser, '.settings-voice-select')
    await wait(browser, '[data-voice-id="44"] .voice-more')
    await click(browser, '[data-voice-id="44"] .voice-more'); await wait(browser, '.voice-action-list')
    await click(browser, '.voice-action-list button'); await wait(browser, '.voice-editor')
    await browser.evaluate(f"{Q}('.voice-editor input').value='URLの声';const s={Q}('.voice-editor select[aria-label=音源]');s.value='url';s.dispatchEvent(new Event('change'));{Q}('.voice-editor input[type=url]').value='https://example.test/invalid.wav'")
    await click(browser, '.voice-editor [type=submit]')
    await fixture.until(browser, f"!{Q}('.voice-editor-error').hidden")
    assert next(v for v in Handler.voices if v['id'] == 44)['name'] == '折木奉太郎'
    await browser.evaluate(f"const u={Q}('.voice-editor input[type=url]');u.value='https://example.test/voice.wav';u.dispatchEvent(new Event('input',{{bubbles:true}}))")
    await screenshot(browser, f'voice-url-editor-{width}.png')
    await click(browser, '.voice-editor [type=submit]'); await wait(browser, '[data-voice-id="44"]')
    assert any(c['path'] == '/api/settings/voices/44' and c['body'].get('file_token') == 'url-wave' for c in Handler.calls)
    assert Handler.mode['browser_voice_name'] == 'ja-JP-KeitaNeural'
    await click(browser, '[data-voice-id="44"] .voice-more'); await wait(browser, '.voice-action-list')
    await click(browser, '.voice-action-list button'); await wait(browser, '.voice-editor')
    await click(browser, '.voice-editor .voice-file-row button')
    await fixture.until(browser, f"{Q}('.voice-file-name').textContent==='sample.wav'")
    await click(browser, '.voice-editor [type=submit]'); await wait(browser, '[data-voice-id="44"]')
    assert any(c['path'] == '/api/settings/voices/44' and c['body'].get('file_token') == 'selected-wave' for c in Handler.calls)
    await click(browser, '.voice-add'); await wait(browser, '.voice-editor')
    await browser.evaluate(f"{Q}('.voice-editor input').value='追加声線'")
    await click(browser, '.voice-editor .voice-file-row button')
    await fixture.until(browser, f"{Q}('.voice-file-name').textContent==='sample.wav'")
    await click(browser, '.voice-editor [type=submit]'); await wait(browser, '[data-voice-id="202"]')
    await click(browser, '[data-voice-id="202"] .voice-more'); await wait(browser, '.voice-action-list')
    await click(browser, '.voice-delete'); await wait(browser, '[data-voice-id="44"]')
    assert not any(v['id'] == 202 for v in Handler.voices)
    assert not await browser.evaluate('window.__layoutErrors.length'), await browser.evaluate('window.__layoutErrors')
    metrics['flows'] = ['inline Keita and Voidoll labels', 'per-voice preview preserved', 'no repeated system item or preset management', 'back and Escape', 'reference preview', 'dictionary speech call', 'URL and file replacement', 'add and delete reference']
    return metrics


async def desktop(browser, base_url, phase):
    Handler.reset(); Handler.phase = phase
    await browser.call('Network.clearBrowserCache')
    await browser.call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
    await browser.call('Page.navigate', {'url': base_url + '/pc'})
    await fixture.until(browser, "document.readyState==='complete'&&typeof showView==='function'")
    await browser.evaluate("showView('settings')")
    await fixture.until(browser, "document.querySelectorAll('#voice-list .voice-row').length===2")
    await browser.evaluate('(async()=>{await document.fonts.ready;await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)})()')
    return await browser.evaluate("""(()=>{const v=document.querySelector('#settings-view'),r=v.getBoundingClientRect(),c=getComputedStyle(v);return {redesign:document.documentElement.hasAttribute('data-redesign-app'),shell:!!window.__fujimiAppRoot,width:r.width,x:r.x,padding:c.padding,background:c.backgroundColor,font:c.font,voiceRows:document.querySelectorAll('#voice-list .voice-row').length,referenceNames:[...document.querySelectorAll('#voice-list .voice-row')].slice(1).map(row=>row.querySelector('.voice-name').textContent),overflow:document.documentElement.scrollWidth>innerWidth,errors:window.__layoutErrors}})()""")


async def run():
    OUT.mkdir(parents=True, exist_ok=True)
    server = fixture.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='fujimi-voice-ui-', ignore_cleanup_errors=True) as temporary:
            profile = Path(temporary) / 'edge'
            process = subprocess.Popen([str(fixture.EDGE), '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + str(profile), 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for _ in range(150):
                    if (profile / 'DevToolsActivePort').exists(): break
                    await asyncio.sleep(.1)
                port, endpoint = (profile / 'DevToolsActivePort').read_text().splitlines()[:2]
                async with aiohttp.ClientSession() as client:
                    async with client.ws_connect(f'http://127.0.0.1:{port}{endpoint}', max_msg_size=32*1024*1024) as socket:
                        browser = fixture.HeadlessRenderer(socket)
                        target = await browser.call('Target.createTarget', {'url': 'about:blank'}, browser=True)
                        browser.session = (await browser.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True}, browser=True))['sessionId']
                        await browser.call('Page.enable')
                        await browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': NATIVE})
                        results = {}
                        for width in (375, 390):
                            results[str(width)] = {}
                            for phase in ('before', 'after'):
                                results[str(width)][phase] = await inspect(browser, f'http://127.0.0.1:{server.server_port}', width, phase)
                        results['1440'] = {}
                        for phase in ('before', 'after'):
                            results['1440'][phase] = await desktop(browser, f'http://127.0.0.1:{server.server_port}', phase)
                        assert results['1440']['before'] == results['1440']['after']
                        assert not results['1440']['after']['redesign'] and not results['1440']['after']['shell']
                        (OUT / 'voice-layout.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
                        print(json.dumps(results, ensure_ascii=False), flush=True)
                        await browser.call('Browser.close', browser=True)
                process.wait(timeout=15)
            finally:
                if process.poll() is None:
                    process.terminate(); process.wait(timeout=15)
    finally:
        server.shutdown(); server.server_close()


if __name__ == '__main__':
    asyncio.run(run())
