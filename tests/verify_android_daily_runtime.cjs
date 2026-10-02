// Actual background alarm / independent worker on this task's isolated emulator.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const adb = 'C:/Android/Sdk/platform-tools/adb.exe';
const serial = 'emulator-5584';
const pkg = 'jp.fujimi.newsbunko.next';
const device = (...args) => execFileSync(adb, ['-s', serial, ...args], {timeout:30000}).toString();
const output = path.resolve(__dirname, '../build/qa/android-daily-runtime');

(async () => {
  const target = (await (await fetch('http://127.0.0.1:9229/json/list')).json()).find(x => x.url.startsWith('https://appassets.androidplatform.net/'));
  assert(target);
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject) => {socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  const callbacks = new Map(); let sequence=0;
  socket.addEventListener('message',e => {const v=JSON.parse(String(e.data)); if(callbacks.has(v.id)){callbacks.get(v.id)(v);callbacks.delete(v.id);}});
  const evaluate = expression => new Promise((resolve,reject) => {
    const id=++sequence;
    const timer=setTimeout(()=>{callbacks.delete(id);reject(new Error('WebView evaluation timeout'));},30000);
    callbacks.set(id,v=>{clearTimeout(timer);const r=v.result;if(v.error||r?.exceptionDetails)reject(new Error(JSON.stringify(v.error||r.exceptionDetails)));else resolve(r.result.value);});
    socket.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true}}));
  });
  const api = (url,method='GET',body) => evaluate(`api(${JSON.stringify(url)},{method:${JSON.stringify(method)}${body===undefined?'':',body:'+JSON.stringify(JSON.stringify(body))}})`);
  const until = async (predicate,limit) => {
    const end=Date.now()+limit;
    while(Date.now()<end) {const result=await predicate();if(result)return result;await new Promise(resolve=>setTimeout(resolve,1000));}
    throw new Error('Background worker timeout');
  };
  device('shell','run-as',pkg,'cp','shared_prefs/mobile-settings.xml','cache/daily-qa-settings.xml');
  const evidence={};
  try {
    const before=await api('/api/tasks/daily');
    if(before.status==='running') await api('/api/tasks/daily','DELETE');
    const sources=await api('/api/settings/news-sources');
    const keep=sources.find(x=>new URL(x.homepage).hostname==='www.yomiuri.co.jp');
    assert(keep);
    for(const source of sources.filter(x=>x.id!==keep.id)) await api('/api/settings/news-sources/'+source.id,'DELETE');
    await api('/api/settings/daily-content','PUT',{target_count:1});
    await evaluate('FujimiMobile.setAllowCellular(false)');
    const epoch=Math.ceil((Date.now()+5000)/60000)*60000;
    const time=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(epoch));
    const alarm=await api('/api/settings/daily-schedule','PUT',{mode:'automatic',time});
    assert.equal(alarm.mode,'automatic');assert(alarm.next_run);assert.equal(alarm.schedule_precision,'exact');
    evidence.alarm=alarm;
    evidence.systemAlarm=device('shell','dumpsys','alarm').split('\n').filter(x=>x.includes(pkg)||x.includes('DAILY_ALARM')).join('\n');
    device('shell','input','keyevent','3');
    console.log('Actual future CST alarm arranged; activity is in background.');
    const automatic=await until(async()=>{const v=await api('/api/tasks/daily');return v.id&&v.id!==before.id&&v.status!=='running'?v:false;},125000);
    assert.equal(automatic.status,'failed');
    assert.match(automatic.message,/计费网络|网络不可用|网络/);
    assert.equal(automatic.percent,0);
    evidence.automatic=automatic;
    console.log(JSON.stringify({automaticStatus:automatic.status,message:automatic.message}));
    await api('/api/settings/daily-schedule','PUT',{mode:'manual',time:'00:00'});
    await evaluate('FujimiMobile.setAllowCellular(true)');
    const start=await api('/api/daily/generate','POST');assert.equal(start.status,'started');
    const trace=[];
    const manual=await until(async()=>{
      const v=await api('/api/tasks/daily');
      const key=v.stage+':'+v.message;
      if(trace.at(-1)!==key) {trace.push(key);console.log(key);}
      return v.status!=='running'?v:false;
    },300000);
    evidence.manual=manual;evidence.trace=trace;
    const editions=await api('/api/daily?date='+manual.date);
    evidence.savedArticles=(editions.articles||[]).map(x=>({id:x.id,title:x.title,paragraphs:x.paragraphs?.length,furigana:x.furigana_paragraphs?.length,imagePaths:x.image_paths,voiceMode:x.voice_mode}));
    assert.equal(evidence.savedArticles.length,manual.completed);
    assert(manual.status==='completed'||manual.percent<100);
    evidence.manualOutcome=manual.completed>0?'real article saved':'network or public-body validation failed honestly; no fabricated content';
    fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(evidence,null,2));
    console.log(JSON.stringify({alarm:'real background trigger',manual:manual.status,saved:manual.completed,output}));
  } finally {
    try {await api('/api/tasks/daily','DELETE');await api('/api/settings/daily-schedule','PUT',{mode:'manual',time:'00:00'});} catch{}
    socket.close();
    device('shell','am','force-stop',pkg);
    device('shell','run-as',pkg,'cp','cache/daily-qa-settings.xml','shared_prefs/mobile-settings.xml');
    device('shell','run-as',pkg,'rm','cache/daily-qa-settings.xml');
    device('shell','appops','set',pkg,'SCHEDULE_EXACT_ALARM','deny');
    device('shell','am','start','-n',pkg+'/.MainActivity');
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
