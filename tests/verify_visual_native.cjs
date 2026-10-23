// Read-only UI acceptance against an isolated Android emulator's real WebView.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const adb = 'C:/Android/Sdk/platform-tools/adb.exe';
const serial = process.env.FUJIMI_TEST_EMULATOR || 'emulator-5554';
assert(/^emulator-\d+$/.test(serial));
const mode = process.argv[2] || 'light';
const headersOnly = process.argv.includes('--headers-only');
const output = path.resolve(__dirname, '../build/qa/android-visual-native');
const device = (...args) => execFileSync(adb, ['-s', serial, ...args], { timeout: 30000 });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const targets = await (await fetch('http://127.0.0.1:9229/json/list')).json();
  const target = targets.find(t => t.url.startsWith('https://appassets.androidplatform.net/'));
  assert(target, 'Real Android asset WebView must exist');
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  let sequence = 0;
  const pending = new Map();
  const errors = [];
  socket.addEventListener('message', event => {
    const result = JSON.parse(String(event.data));
    if (result.method === 'Runtime.exceptionThrown') errors.push(result.params.exceptionDetails.exception?.description || result.params.exceptionDetails.text);
    if (pending.has(result.id)) { pending.get(result.id)(result); pending.delete(result.id); }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(method + ' timed out')); }, 30000);
    pending.set(id, result => { clearTimeout(timer); result.error ? reject(new Error(JSON.stringify(result.error))) : resolve(result.result); });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const response = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    return response.result.value;
  };
  const waitFor = async condition => {
    for (let i=0;i<100;i++) { if (await evaluate(`Boolean(${condition})`)) return; await delay(100); }
    throw new Error('Condition not reached: ' + condition);
  };
  const touch = async selector => {
    const p = await evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)});if(!e||e.disabled)throw Error('Missing or disabled ${selector}');e.scrollIntoView({block:'center',inline:'nearest'});const r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;if(!r.width||!r.height||x<0||y<0||x>innerWidth||y>innerHeight||!e.contains(document.elementFromPoint(x,y)))throw Error('Unreachable or covered ${selector}');return{x,y}})()`);
    await send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{...p,radiusX:1,radiusY:1}]});
    await send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    await delay(250);
  };
  const screenshot = async name => {
    const png=await send('Page.captureScreenshot',{format:'png'});
    fs.writeFileSync(path.join(output,`${mode}-${name}-webview.png`),Buffer.from(png.data,'base64'));
    await delay(180);
    fs.writeFileSync(path.join(output, `${mode}-${name}-native.png`),device('exec-out','screencap','-p'));
  };
  const metrics = async () => evaluate(`(() => {
    const bounds = s => {const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect(),c=getComputedStyle(e);return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height,fontSize:c.fontSize,lineHeight:c.lineHeight,scrollHeight:e.scrollHeight,clientHeight:e.clientHeight}};
    const probe=document.createElement('div');probe.style.cssText='position:fixed;visibility:hidden;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)';document.body.append(probe);const style=getComputedStyle(probe);const safe={top:parseFloat(style.paddingTop),bottom:parseFloat(style.paddingBottom)};probe.remove();
    const rootStyle=getComputedStyle(document.documentElement),nativeSafe=Object.fromEntries(['top','right','bottom','left'].map(edge=>[edge,parseFloat(rootStyle.getPropertyValue('--native-safe-area-'+edge))||0]));
    return {route:location.hash,width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,dpr:devicePixelRatio,dark:matchMedia('(prefers-color-scheme: dark)').matches,safe,nativeSafe,bar:bounds('.mobile-app-bar'),nav:bounds('#mobile-nav-toggle'),kicker:bounds('#mobile-current-kicker'),title:bounds('#mobile-current-view'),description:bounds('#mobile-current-description'),shell:bounds('.content-shell'),sidebarShadow:getComputedStyle(document.querySelector('#primary-sidebar')).boxShadow,background:getComputedStyle(document.body).backgroundColor,buttons:[...document.querySelectorAll('.view:not([hidden]) button')].filter(e=>e.getClientRects().length).map(e=>({id:e.id,label:e.textContent.trim().slice(0,40),width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})),version:document.querySelector('#mobile-app-version')?.textContent};
  })()`);
  const results = {mode,device:serial,fontScale:device('shell','settings','get','system','font_scale').toString().trim(),nightMode:device('shell','cmd','uimode','night').toString().trim(),routes:[],menus:[]};
  try {
    await send('Runtime.enable');
    await waitFor("typeof showView==='function' && !document.documentElement.classList.contains('mobile-app-booting')");
    for (const route of ['daily','reader','bookmarks','library','dictionary','settings']) {
      if(headersOnly) {
        await evaluate(`showView(${JSON.stringify(route)})`);
      } else {
        await touch('#mobile-nav-toggle');
        await waitFor("document.documentElement.dataset.mobileNavOpen==='true'");
        if(route==='daily') { await screenshot('drawer');results.menus.push({name:'drawer',metrics:await metrics()}); }
        await touch('#primary-sidebar [data-view="'+route+'"]');
      }
      await waitFor(`state.currentView===${JSON.stringify(route)} && document.documentElement.dataset.mobileNavOpen==='false'`);
      await evaluate('window.scrollTo(0,0)');
      await delay(450);
      const result=await metrics();results.routes.push(result);
      await screenshot(route);
      assert(result.scrollWidth<=result.width+1,'Horizontal overflow on '+route);
      assert.equal(result.dark,results.nightMode.includes('yes'),'WebView color scheme must follow the Android night mode');
      assert(result.nativeSafe.top>0,'Native status-bar inset must reach the edge-to-edge WebView');
      assert(result.kicker.top>=result.nativeSafe.top,'Header kicker must sit below native status bar');
      assert(result.description.bottom<=result.bar.bottom,'Header description must stay inside the bar at the Android font scale');
    }
    if(headersOnly) { results.errors=errors;assert.equal(errors.length,0);console.log(JSON.stringify(results.routes.map(r=>({route:r.route,barBottom:r.bar.bottom,titleBottom:r.title.bottom,descriptionBottom:r.description.bottom,nativeSafe:r.nativeSafe})),null,2));return; }
    await touch('[data-android-select="library-sort-setting"]');
    await waitFor("document.querySelector('[data-android-select=library-sort-setting]').getAttribute('aria-expanded')==='true'");
    await screenshot('settings-sort-menu');
    device('shell','input','keyevent','4');
    await waitFor("document.querySelector('[data-android-select=library-sort-setting]').getAttribute('aria-expanded')==='false'");
    results.menus.push({name:'library-sort',backClosed:true});
    await touch('#add-voice');
    await waitFor("document.querySelector('#voice-dialog').open");
    if(await evaluate("!document.querySelector('#browser-voice-row').hidden")) {
      await touch('[data-android-select="browser-voice-select"]');
      await waitFor("document.querySelector('[data-android-select=browser-voice-select]').getAttribute('aria-expanded')==='true'");
      await screenshot('voice-menu');
      device('shell','input','keyevent','4');
      await waitFor("document.querySelector('[data-android-select=browser-voice-select]').getAttribute('aria-expanded')==='false'");
      assert.equal(await evaluate("document.querySelector('#voice-dialog').open"),true);
    } else {
      device('shell','input','keyevent','4');
      await delay(350);
      await screenshot('voice-dialog');
    }
    await touch('#close-voice-dialog');
    await waitFor("!document.querySelector('#voice-dialog').open");
    results.menus.push({name:'voice-menu',backClosed:true});
    await evaluate("showView('reader')");
    await touch('#open-web-text-dialog');
    await waitFor("document.querySelector('#web-text-dialog').open");
    assert.equal((await metrics()).nativeSafe.bottom,results.routes[0].nativeSafe.bottom,'Soft keyboard must not inflate the system-bar safe area');
    await screenshot('paste-dialog');
    await touch('#close-web-text-dialog');
    results.menus.push({name:'paste-dialog',closed:true});
    results.errors=errors;
    assert.equal(errors.length,0,'WebView must not raise JavaScript exceptions');
    fs.writeFileSync(path.join(output,`${mode}-results.json`),JSON.stringify(results,null,2));
    console.log(JSON.stringify({mode,checks:results.routes.map(r=>({route:r.route,width:r.width,scrollWidth:r.scrollWidth,safe:r.safe,bar:r.bar,title:r.title,description:r.description})),menus:results.menus.filter(m=>!m.metrics),errors},null,2));
  } finally { fs.writeFileSync(path.join(output,`${mode}-results.json`),JSON.stringify(results,null,2));socket.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
