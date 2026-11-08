"""Visual and interaction acceptance of the rebuilt demo with the real library."""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import tempfile

import aiohttp
from PIL import Image, ImageDraw, ImageFont
from render_designs import HeadlessRenderer, EDGE, OUT
from verify_real_preview import real_state


async def until(browser, expression, message):
    for _ in range(180):
        if await browser.evaluate(expression): return
        await asyncio.sleep(.05)
    raise AssertionError(message)


async def screenshot(browser, name, width):
    if name == 'voices': await browser.evaluate('window.__redesignRoot.activeElement?.blur()')
    await browser.evaluate("(async()=>{await document.fonts.ready;await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);const r=window.__redesignRoot;await Promise.all([...r.querySelectorAll('img')].filter(i=>i.checkVisibility()&&i.getBoundingClientRect().top<innerHeight).map(i=>i.decode().catch(()=>{})))})()")
    data = await browser.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
    (OUT / f'v2-{name}-{width}.png').write_bytes(base64.b64decode(data['data']))


async def run():
    original = real_state()
    results = []
    with tempfile.TemporaryDirectory(prefix='fujimi-v2-ui-') as temporary:
        profile = Path(temporary) / 'edge'
        process = subprocess.Popen([str(EDGE), '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking',
                                    '--remote-debugging-port=0', '--user-data-dir=' + str(profile), 'about:blank'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                if (profile / 'DevToolsActivePort').exists(): break
                await asyncio.sleep(.1)
            port, endpoint = (profile / 'DevToolsActivePort').read_text().splitlines()[:2]
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(f'http://127.0.0.1:{port}{endpoint}', max_msg_size=32 * 1024 * 1024) as socket:
                    browser = HeadlessRenderer(socket)
                    target = await browser.call('Target.createTarget', {'url': 'about:blank'}, browser=True)
                    browser.session = (await browser.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True}, browser=True))['sessionId']
                    try:
                        await browser.call('Page.enable')
                        await browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': "window.__uiErrors=[];addEventListener('error',e=>__uiErrors.push(e.message));addEventListener('unhandledrejection',e=>__uiErrors.push(String(e.reason?.message||e.reason)))"})
                        for width in [375, 390]:
                            await browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
                            await browser.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
                            await browser.call('Page.navigate', {'url': f'http://127.0.0.1:8499/native-app.html?check={width}#preview/daily'})
                            await until(browser, "window.__newPreview?.ready&&window.__redesignRoot?.querySelector('.news-item')&&!!window.__redesignRoot.querySelector('link').sheet", 'New interface did not load')
                            for view in ['daily', 'reader', 'library', 'dictionary', 'settings', 'bookmarks']:
                                await browser.evaluate(f"window.__redesignNavigate('{view}')")
                                await until(browser, "!window.__redesignRoot.querySelector('.loading')", 'Page did not finish loading')
                                metrics = await browser.evaluate("(()=>{const r=window.__redesignRoot,m=r.querySelector('.page-main'),n=r.querySelector('.bottom-nav');return {view:window.__newPreview.view,width:innerWidth,documentWidth:document.documentElement.scrollWidth,contentWidth:m.clientWidth,contentScroll:m.scrollWidth,pageHeight:m.scrollHeight,nav:[...n.children].map(x=>({text:x.textContent,top:x.getBoundingClientRect().top})),cards:r.querySelectorAll('.news-item').length,errors:window.__uiErrors}})()")
                                assert metrics['documentWidth'] <= width and metrics['contentScroll'] <= metrics['contentWidth'], metrics
                                assert len({item['top'] for item in metrics['nav']}) == 1, metrics
                                assert [item['text'] for item in metrics['nav']] == ['日刊', '閲読室', '書架', '辞書', '设置'], metrics
                                assert not metrics['errors'], metrics
                                if view == 'daily':
                                    details = await browser.evaluate("(()=>{const r=window.__redesignRoot;return {footers:r.querySelectorAll('.card-audio-state').length,metadata:[...r.querySelectorAll('.news-meta')].map(x=>x.getBoundingClientRect().height),compact:[...r.querySelectorAll('.news-item:not(.featured)')].map(x=>({height:x.getBoundingClientRect().height,title:x.querySelector('h2').getBoundingClientRect().height,image:x.querySelector('img')?.getBoundingClientRect().height||0}))}})()")
                                    assert details['footers'] == 0 and max(details['metadata']) < 17, details
                                    assert all(item['height'] <= max(item['title'], item['image']) + 65 for item in details['compact']), details
                                if view == 'reader':
                                    order = await browser.evaluate("(()=>{const r=window.__redesignRoot,input=r.querySelector('#room-url').getBoundingClientRect(),submit=r.querySelector('.link-form .primary').getBoundingClientRect(),paste=r.querySelector('.paste-action').getBoundingClientRect();return {inputBottom:input.bottom,submitTop:submit.top,submitBottom:submit.bottom,pasteTop:paste.top}})()")
                                    assert order['inputBottom'] < order['submitTop'] and order['submitBottom'] < order['pasteTop'], order
                                if view == 'library':
                                    layout = await browser.evaluate("(()=>{const r=window.__redesignRoot,h=r.querySelector('h1').getBoundingClientRect(),a=r.querySelector('.pill-action').getBoundingClientRect();return {h:h.top,a:a.top,width:a.width,covers:r.querySelectorAll('.book-tile img').length,continueCards:r.querySelectorAll('.continue-card').length}})()")
                                    assert abs(layout['h'] - layout['a']) < 10 and layout['width'] < 85 and layout['covers'] > 0 and layout['continueCards'] == 0, layout
                                if view == 'dictionary':
                                    flow = await browser.evaluate("(()=>{const r=window.__redesignRoot,h=r.querySelector('.dictionary-heading').getBoundingClientRect(),s=r.querySelector('.search-box').getBoundingClientRect(),help=r.querySelector('.search-help').getBoundingClientRect();return {headingBottom:h.bottom,searchTop:s.top,searchBottom:s.bottom,helpTop:help.top}})()")
                                    assert flow['headingBottom'] + 15 <= flow['searchTop'] and flow['searchBottom'] < flow['helpTop'], flow
                                if view == 'settings':
                                    assert metrics['pageHeight'] < 1250, metrics
                                    compact = await browser.evaluate("({inputs:window.__redesignRoot.querySelectorAll('main input').length,voices:window.__redesignRoot.querySelectorAll('.voice-card').length,rows:window.__redesignRoot.querySelectorAll('.setting-row').length})")
                                    assert compact['inputs'] == 1 and compact['voices'] == 1 and compact['rows'] <= 9, compact
                                await screenshot(browser, view, width)
                                results.append(metrics)
                                print(json.dumps({'view': view, 'width': width, 'page_height': metrics['pageHeight'], 'passed': True}), flush=True)
                            # Real dictionary query and detail, beyond the initial empty state.
                            await browser.evaluate("window.__redesignNavigate('dictionary')")
                            await browser.evaluate("(()=>{const r=window.__redesignRoot;r.querySelector('#word-query').value='余白';r.querySelector('form').requestSubmit()})()")
                            await until(browser, "!!window.__redesignRoot.querySelector('.word-result')", 'Real dictionary search failed')
                            await browser.evaluate("window.__redesignRoot.querySelector('.word-result').click()")
                            await until(browser, "window.__redesignRoot.querySelector('.word-title-row h2')?.textContent==='余白'", 'Real word detail failed')
                            await screenshot(browser, 'word', width)
                            # A genuine selection panel, instead of an unchanged long form.
                            await browser.evaluate("window.__redesignNavigate('settings')")
                            await browser.evaluate("[...window.__redesignRoot.querySelectorAll('button')].find(x=>x.textContent==='切换').click()")
                            await until(browser, "window.__redesignRoot.querySelector('dialog').open", 'Voice sheet failed')
                            assert await browser.evaluate("window.__redesignRoot.querySelectorAll('dialog .choice').length>=14")
                            await screenshot(browser, 'voices', width)
                            await browser.evaluate("window.__redesignRoot.querySelector('dialog').close()")
                            # Open real native EPUB content, then return to the new shelf.
                            await browser.evaluate("window.__redesignNavigate('library')")
                            await browser.evaluate("window.__redesignRoot.querySelector('.book-tile').click()")
                            await until(browser, "document.documentElement.dataset.nativeReading==='book'&&document.querySelectorAll('#book-reader .book-block').length>0", 'Native book did not open')
                            await screenshot(browser, 'book-reader', width)
                            await browser.evaluate("document.querySelector('#book-reader .back-to-library').click()")
                            await until(browser, "!document.documentElement.dataset.nativeReading&&window.__newPreview.view==='library'&&!window.__redesignRoot.querySelector('.loading')", 'Return from book failed')
                            # Open and return from a real article without changing it.
                            await browser.evaluate("window.__redesignNavigate('daily')")
                            await browser.evaluate("window.__redesignRoot.querySelector('.news-item').click()")
                            await until(browser, "document.documentElement.dataset.nativeReading==='article'&&!!document.querySelector('#reader-result .article-detail')", 'Real article did not open')
                            await screenshot(browser, 'article', width)
                            await browser.evaluate("window.__redesignRoot.querySelector('.reader-bar button').click()")
                            await until(browser, "!document.documentElement.dataset.nativeReading&&window.__newPreview.view==='daily'", 'Return from article failed')
                            assert not await browser.evaluate('window.__uiErrors')
                    finally:
                        await browser.call('Browser.close', browser=True)
        finally:
            process.wait(timeout=15)
    assert real_state() == original, 'Formal library settings or reading progress changed'
    (OUT / 'v2-verification.json').write_text(json.dumps({'screens': results, 'formal_data_unchanged': True, 'real_dictionary': True, 'voice_sheet': True, 'native_readers': True}, ensure_ascii=False, indent=2), encoding='utf-8')
    make_overview()
    print(json.dumps({'screens_passed': len(results), 'formal_data_unchanged': True}), flush=True)


def make_overview():
    items = [('daily', '日刊'), ('reader', '閲読室'), ('library', '書架'), ('dictionary', '辞書'), ('settings', '設置'), ('voices', '声の形')]
    width, height, gap, margin = 351, 760, 36, 48
    canvas = Image.new('RGB', (margin * 2 + width * 3 + gap * 2, 132 + (height + 65) * 2 + gap + 44), '#e9ece3')
    draw = ImageDraw.Draw(canvas)
    font = lambda size: ImageFont.truetype('C:/Windows/Fonts/NotoSansSC-VF.ttf', size)
    serif = lambda size: ImageFont.truetype('C:/Windows/Fonts/NotoSerifSC-VF.ttf', size)
    draw.rectangle((margin, 34, margin + 5, 82), fill='#a33f31')
    draw.text((margin + 21, 30), '富士見新聞文庫 · 手机端重制', font=serif(30), fill='#26312f')
    draw.text((margin + 21, 80), '真实文库 / 新页面结构 / 底栏直达设置', font=font(13), fill='#697660')
    for index, (name, label) in enumerate(items):
        x = margin + (index % 3) * (width + gap)
        y = 132 + (index // 3) * (height + 65 + gap)
        with Image.open(OUT / f'v2-{name}-390.png') as image:
            canvas.paste(image.convert('RGB').resize((width, height), Image.Resampling.LANCZOS), (x, y))
        draw.text((x, y + height + 16), label, font=serif(21), fill='#26312f')
    canvas.save(OUT / 'design-v2-overview.png')


if __name__ == '__main__':
    asyncio.run(run())
