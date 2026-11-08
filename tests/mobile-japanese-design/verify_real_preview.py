"""Read-only acceptance against the running library, in an isolated browser.

All browser writes are contained by serve_demo's preview overlay. No fixture
content is injected; the final assertion compares formal settings and progress.
"""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import tempfile

import aiohttp
import requests
from render_designs import HeadlessRenderer, EDGE, OUT


def real_state():
    with requests.Session() as session:
        session.trust_env = False
        base = 'http://127.0.0.1:8428/api/'
        books = session.get(base + 'books', timeout=20).json()['books']
        return {'voice': session.get(base + 'settings/voice-mode', timeout=20).json(),
                'bookmarks': session.get(base + 'bookmarks', timeout=20).json(),
                'progress': {book['id']: book['progress'] for book in books}}


async def verify():
    original = real_state()
    results = []
    with tempfile.TemporaryDirectory(prefix='fujimi-live-preview-') as temporary:
        profile = Path(temporary) / 'edge'
        process = subprocess.Popen([str(EDGE), '--headless=new', '--disable-gpu', '--no-first-run',
                                    '--disable-background-networking', '--remote-debugging-port=0',
                                    '--user-data-dir=' + str(profile), 'about:blank'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                if (profile / 'DevToolsActivePort').exists(): break
                await asyncio.sleep(.1)
            port, path = (profile / 'DevToolsActivePort').read_text().splitlines()[:2]
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(f'http://127.0.0.1:{port}{path}', max_msg_size=32 * 1024 * 1024) as socket:
                    browser = HeadlessRenderer(socket)
                    target = await browser.call('Target.createTarget', {'url': 'about:blank'}, browser=True)
                    browser.session = (await browser.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True}, browser=True))['sessionId']
                    try:
                        await browser.call('Page.enable')
                        for width in [375, 390]:
                            await browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
                            await browser.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
                            await browser.call('Page.navigate', {'url': 'http://127.0.0.1:8499/app#daily'})
                            for _ in range(150):
                                if await browser.evaluate("document.querySelectorAll('#daily-list .news-card').length>0&&!!document.querySelector('.preview-date-row')"): break
                                await asyncio.sleep(.05)
                            steps = [
                                ('daily', 'true'),
                                ('library', "(async()=>{history.replaceState({view:'library'},'','#library');await showView('library');await loadLibrary({forceHome:true})})()"),
                                ('settings', "showView('settings')"),
                                ('dictionary', "(async()=>{await showView('dictionary');await searchDictionary('余白')})()"),
                                ('article', "(async()=>{const days=await api('/api/days');const day=await api('/api/daily?date='+days[0]);const a=day.articles.find(x=>x.audio_path)||day.articles[0];await openArticleInReader(a)})()"),
                                ('book', "(async()=>{await showView('library');const all=await api('/api/books');const b=all.books[0];await navigateBookChapter(b.id,b.progress?.chapter_id||b.chapters[0].id)})()")
                            ]
                            for view, expression in steps:
                                await browser.evaluate(expression)
                                await browser.evaluate('(async()=>{await document.fonts.ready;await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)})()')
                                await browser.evaluate("Promise.all([...document.images].filter(i=>i.getBoundingClientRect().top<innerHeight&&i.getBoundingClientRect().bottom>0&&i.checkVisibility()).map(i=>i.decode().catch(()=>{})))")
                                metrics = await browser.evaluate("(()=>{const n=document.querySelector('.preview-bottom-nav'),h=document.querySelector('.view:not([hidden]) .section-head');return{viewport:innerWidth,width:document.documentElement.scrollWidth,view:state.currentView,reading:document.documentElement.dataset.previewReading||'',cards:document.querySelectorAll('#daily-list>.news-card').length,images:document.querySelectorAll('.preview-card-image').length,navRows:[...n.children].map(x=>Math.round(x.getBoundingClientRect().top)),navVisible:getComputedStyle(n).display!=='none',headingVisible:h?getComputedStyle(h).display!=='none':null,voice:state.browserVoiceName}})()")
                                assert metrics['viewport'] == width and metrics['width'] <= width, (view, metrics)
                                if metrics['navVisible']: assert len(set(metrics['navRows'])) == 1, metrics
                                assert metrics['cards'] > 0 and metrics['images'] > 0, metrics
                                if view == 'daily': assert metrics['headingVisible'], metrics
                                if view == 'book': assert metrics['reading'] == 'book', metrics
                                screenshot = await browser.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
                                (OUT / f'live-demo-{view}-{width}.png').write_bytes(base64.b64decode(screenshot['data']))
                                results.append({'screen': view, **metrics})
                                print(json.dumps(results[-1], ensure_ascii=False), flush=True)
                            # Returning from a real book must restore primary navigation.
                            await browser.evaluate("document.querySelector('#book-reader .back-to-library').click()")
                            for _ in range(100):
                                if await browser.evaluate("document.documentElement.dataset.previewReading===''&&getComputedStyle(document.querySelector('.preview-bottom-nav')).display!=='none'"): break
                                await asyncio.sleep(.05)
                            else: raise AssertionError('Book return did not restore navigation')
                    finally:
                        await browser.call('Browser.close', browser=True)
        finally:
            process.wait(timeout=15)
    assert real_state() == original, 'Formal library settings or progress changed'
    (OUT / 'live-demo-verification.json').write_text(json.dumps({'checks': results, 'formal_data_unchanged': True}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'layout_checks': len(results), 'formal_data_unchanged': True}), flush=True)


if __name__ == '__main__':
    asyncio.run(verify())
