import json
import json
from pathlib import Path
import subprocess
import unittest
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]


class FrontendBehaviorTests(unittest.TestCase):
    def test_browser_speech_waits_for_next_paragraph_to_start_before_highlighting(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const utterances = [];
const sections = [0, 1].map(index => ({
  dataset: { audioIndex: String(index) }, active: false,
  classList: { toggle(_name, value) { sections[index].active = value; } },
  setAttribute() {}, removeAttribute() {},
}));
const root = { querySelectorAll: () => sections };
const progress = { max: 0, value: 0 };
const player = { hidden: true };
const model = { text: '一段目。\n次の段落。', segments: [{ start: 0, end: 4 }, { start: 5, end: 10 }] };
const controller = {
  root, ...model, textLength: model.text.length, index: 0, token: 0,
  rate: 1, duration: 5, playing: false, started: false, cancelled: false,
};
const context = {
  state: { browserSpeech: controller },
  window: {},
  $: selector => selector === '.article-audio-player' ? player : progress,
  renderAudioPlayerChrome: () => {},
  stopDesktopOnlineAudio: () => {}, stopLocalBrowserAudio: () => {}, stopSpeechEngine: () => {},
  resolveJapaneseBrowserVoice: async () => ({ name: 'Japanese', lang: 'ja-JP' }),
  SpeechSynthesisUtterance: class { constructor(text) { this.text = text; utterances.push(this); } },
  speechSynthesis: { speak: () => {} }, startBrowserSpeechTimer: () => {},
  clearInterval: () => {}, notice: () => {},
};
vm.createContext(context);
for (const [start, end] of [
  ['function setActiveAudioParagraph(', 'function bindParagraphSeeking('],
  ['function renderBrowserSpeech(', 'function stopBrowserSpeech('],
  ['async function speakBrowserSpeech(', 'function setupBrowserArticlePlayer('],
]) vm.runInContext(source.slice(source.indexOf(start), source.indexOf(end)), context);
(async () => {
  await context.speakBrowserSpeech(controller);
  utterances[0].onstart?.();
  utterances[0].onboundary({ charIndex: 5 });
  const beforeEnd = sections.map(section => section.active);
  utterances[0].onend();
  const between = sections.map(section => section.active);
  utterances[1]?.onstart?.();
  const nextStarted = sections.map(section => section.active);
  console.log(JSON.stringify({ beforeEnd, between, nextStarted, spoken: utterances.map(item => item.text) }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'beforeEnd': [True, False], 'between': [False, False],
            'nextStarted': [False, True], 'spoken': ['一段目。', '次の段落。'],
        })

    def test_desktop_online_speech_continues_chunks_and_stops_audio(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function stopDesktopOnlineAudio(');
const end = source.indexOf('async function speakBrowserSpeech(', start);
const requests = [];
const audios = [];
const revoked = [];
const controller = {
  text: 'あ'.repeat(1300), index: 0, token: 1, rate: 1,
  cancelled: false, playing: true, started: true,
};
const context = {
  state: { browserSpeech: controller }, AbortController,
  synthesizeDesktopOnlineSpeech: async (text, voice) => { requests.push([text.length, voice.id]); return {}; },
  URL: { createObjectURL: () => `blob:${audios.length}`, revokeObjectURL: url => revoked.push(url) },
  Audio: class {
    constructor(url) { this.url = url; this.duration = 1; this.currentTime = 0; audios.push(this); }
    play() { return Promise.resolve(); }
    pause() { this.paused = true; }
  },
  renderBrowserSpeech: () => {}, notice: () => {},
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.speakDesktopOnlineChunk(controller, { id: 'ja-JP-KeitaNeural' }, 1);
  audios[0].onended();
  await new Promise(resolve => setTimeout(resolve, 0));
  context.stopDesktopOnlineAudio(controller);
  console.log(JSON.stringify({ requests, count: audios.length, stopped: audios[1].paused, revoked }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'requests': [[1200, 'ja-JP-KeitaNeural'], [100, 'ja-JP-KeitaNeural']],
            'count': 2, 'stopped': True, 'revoked': ['blob:0', 'blob:1'],
        })

    def test_reread_uses_one_browser_option_from_shared_voice_setting(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('async function populateRereadVoices(');
const end = source.indexOf('function copyWithoutRuby(', start);
const mode = { mode: 'browser', browser_voice_name: 'Microsoft Keita Online (Natural) - Japanese (Japan)', browser_voice_label: 'ブラウザー' };
const select = { options: [], replaceChildren(...options) { this.options = options; this.value = options[0]?.value; } };
const context = {
  api: async path => path.endsWith('/voices') ? [] : mode,
  state: { browserVoiceName: '', browserVoiceLabel: '' },
  applyBrowserVoiceSettings: settings => { context.state.browserVoiceName = settings.browser_voice_name; context.state.browserVoiceLabel = settings.browser_voice_label; },
  browserVoiceShortName: () => '圭太',
  desktopOnlineVoices: () => [{ id: 'ja-JP-KeitaNeural', name: mode.browser_voice_name }],
  Option: class { constructor(label, value) { this.label = label; this.value = value; } },
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.populateRereadVoices(select, { audio_voice_mode: 'browser' });
  console.log(JSON.stringify({ values: select.options.map(option => option.value), labels: select.options.map(option => option.label), selected: select.value }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {'values': ['browser'], 'labels': ['ブラウザー音声（圭太）'], 'selected': 'browser'})

    def test_cached_online_reread_uses_existing_japanese_notice(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('async function rereadArticle(');
const end = source.indexOf('async function cancelReread(', start);
const messages = [];
const context = {
  window: { FujimiDesktop: true }, state: { browserVoiceName: 'Keita' },
  desktopOnlineVoice: () => ({ id: 'ja-JP-KeitaNeural' }),
  setRereadTask: () => {},
  api: async () => ({ status: 'ready', cached: true, article: { id: 7 } }),
  openArticle: () => {}, toast: message => messages.push(message),
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.rereadArticle({ id: 7 }, 'browser', {}, {});
  console.log(JSON.stringify(messages));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), ['保存済みの朗読を読み込みました。'])

    def test_article_browser_player_uses_global_desktop_online_voice(self):
        source = (ROOT / 'static/main.js').read_text(encoding='utf-8')
        self.assertIn("browserVoiceName: article.example_browser_voice_name || state.browserVoiceName || ''", source)

    def test_desktop_voice_choices_include_edge_online_voices_only_in_desktop(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function japaneseBrowserVoices()');
const end = source.indexOf('function configuredBrowserVoice()', start);
const context = { window: { FujimiDesktop: true, speechSynthesis: {} }, speechSynthesis: { getVoices: () => [] } };
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
const desktop = context.desktopOnlineVoices().map(voice => voice.name);
context.window.FujimiDesktop = false;
const web = context.desktopOnlineVoices().map(voice => voice.name);
console.log(JSON.stringify({ desktop, web }));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'desktop': ['Microsoft Keita Online (Natural) - Japanese (Japan)',
                        'Microsoft Nanami Online (Natural) - Japanese (Japan)'],
            'web': [],
        })

    def test_browser_voice_choices_exclude_legacy_windows_voices(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function japaneseBrowserVoices()');
const end = source.indexOf('function desktopOnlineVoices()', start);
const voices = [
  { name: 'Microsoft Haruka - Japanese (Japan)', lang: 'ja-JP' },
  { name: 'Microsoft Ichiro - Japanese (Japan)', lang: 'ja-JP' },
  { name: 'Microsoft Sayaka - Japanese (Japan)', lang: 'ja-JP' },
  { name: 'Microsoft Ayumi - Japanese (Japan)', lang: 'ja-JP' },
  { name: 'Microsoft Nanami Online (Natural) - Japanese (Japan)', lang: 'ja-JP' },
  { name: 'Microsoft Custom - Japanese (Japan)', lang: 'ja-JP' },
];
const context = { window: { speechSynthesis: {} }, speechSynthesis: { getVoices: () => voices } };
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
console.log(JSON.stringify(context.japaneseBrowserVoices().map(voice => voice.name)));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [
            'Microsoft Nanami Online (Natural) - Japanese (Japan)',
            'Microsoft Custom - Japanese (Japan)',
        ])

    def test_removed_saved_browser_voice_falls_back_to_available_voice(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function japaneseBrowserVoices()');
const end = source.indexOf('function browserVoiceShortName(', start);
const haruka = { name: 'Microsoft Haruka - Japanese (Japan)', lang: 'ja-JP', default: true };
const nanami = { name: 'Microsoft Nanami - Japanese (Japan)', lang: 'ja-JP' };
const context = {
  window: { speechSynthesis: {} },
  speechSynthesis: {
    getVoices: () => [haruka, nanami],
    addEventListener: () => {}, removeEventListener: () => {},
  },
  state: { browserVoiceName: '' },
  setInterval, clearInterval, setTimeout, clearTimeout,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  const voice = await context.resolveJapaneseBrowserVoice({ preferredName: haruka.name });
  console.log(JSON.stringify(voice && voice.name));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), 'Microsoft Nanami - Japanese (Japan)')

    def test_removed_desktop_voice_falls_back_to_online_voice(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function japaneseBrowserVoices()');
const end = source.indexOf('function browserVoiceShortName(', start);
const savedName = 'Microsoft Haruka - Japanese (Japan)';
const writes = [];
const context = {
  window: { FujimiDesktop: true, speechSynthesis: {} },
  speechSynthesis: {
    getVoices: () => [{ name: savedName, lang: 'ja-JP' }],
    addEventListener: () => {}, removeEventListener: () => {},
  },
  state: { browserVoiceName: savedName, browserVoiceLabel: 'ブラウザー' },
  api: async (_, options) => writes.push(JSON.parse(options.body)),
  setInterval, clearInterval, setTimeout, clearTimeout,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  const voice = await context.resolveJapaneseBrowserVoice({ persistDefault: true });
  console.log(JSON.stringify({ voice: voice?.name || null, selected: context.state.browserVoiceName, writes }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        online_name = 'Microsoft Keita Online (Natural) - Japanese (Japan)'
        self.assertEqual(json.loads(result.stdout), {
            'voice': online_name, 'selected': online_name,
            'writes': [{'name': online_name, 'label': 'ブラウザー'}],
        })

    def test_desktop_marker_is_set_before_main_script_runs(self):
        page = BeautifulSoup((ROOT / 'static/index.html').read_text(encoding='utf-8'), 'html.parser')
        boot = page.head.find('script').string
        script = f'''
const vm = require('vm');
const boot = {json.dumps(boot)};
function run(search) {{
  const window = {{ location: {{ search }}, matchMedia: () => ({{ matches: false }}) }};
  const document = {{ documentElement: {{ dataset: {{}}, classList: {{ add: () => {{}} }} }} }};
  vm.runInNewContext(boot, {{ window, document, URLSearchParams }});
  return window.FujimiDesktop;
}}
console.log(JSON.stringify([run('?desktop=1'), run('')]));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [True, False])

    def test_desktop_browser_voice_uses_shared_setting(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function japaneseBrowserVoices()');
const end = source.indexOf('function browserVoiceShortName(', start);
const storage = new Map();
const writes = [];
const mode = { browser_voice_name: 'Microsoft Keita Online (Natural) - Japanese (Japan)', browser_voice_label: 'ブラウザー' };
const haruka = { name: 'Microsoft Haruka - Japanese (Japan)', lang: 'ja-JP', default: true };
const ichiro = { name: 'Microsoft Ichiro - Japanese (Japan)', lang: 'ja-JP' };
const context = {
  window: { FujimiDesktop: true, speechSynthesis: {} },
  speechSynthesis: { getVoices: () => [haruka, ichiro], addEventListener: () => {}, removeEventListener: () => {} },
  localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
  state: { browserVoiceName: '', browserVoiceLabel: '' },
  api: async (path, options) => { if (options) writes.push(path); return mode; },
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.initializeBrowserVoice();
  const first = context.state.browserVoiceName;
  context.applyBrowserVoiceSettings(mode);
  console.log(JSON.stringify({
    first,
    afterReload: context.state.browserVoiceName,
    stored: [...storage.values()].map(value => JSON.parse(value)),
    writes,
  }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
    'first': 'Microsoft Keita Online (Natural) - Japanese (Japan)',
    'afterReload': 'Microsoft Keita Online (Natural) - Japanese (Japan)',
    'stored': [],
    'writes': [],
        })

    def test_desktop_voice_editor_writes_shared_api_like_web(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const voiceStart = source.indexOf('function japaneseBrowserVoices()');
const voiceEnd = source.indexOf('function browserVoiceShortName(', voiceStart);
const editorStart = source.indexOf('async function submitVoiceEditor(');
const editorEnd = source.indexOf('function libraryRoute(', editorStart);
const storage = new Map();
const writes = [];
const custom = { name: 'Microsoft Custom - Japanese (Japan)', lang: 'ja-JP' };
const fields = {
  '#browser-voice-select': { value: custom.name },
  '#voice-editor-name': { value: '自定义' },
};
const context = {
  window: { FujimiDesktop: true, speechSynthesis: {} },
  speechSynthesis: { getVoices: () => [custom] },
  localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
  state: { editingBrowserVoice: true, browserVoiceName: '', browserVoiceLabel: '' },
  $: selector => fields[selector],
  api: async (path, options) => { writes.push({ path, body: JSON.parse(options.body) }); },
  closeVoiceDialog: () => {}, loadVoices: async () => {}, toast: () => {}, panelNotice: () => {},
};
vm.createContext(context);
vm.runInContext(source.slice(voiceStart, voiceEnd), context);
vm.runInContext(source.slice(editorStart, editorEnd), context);
(async () => {
  await context.submitVoiceEditor({ preventDefault() {} });
  const desktop = [...storage.values()].map(value => JSON.parse(value));
  context.window.FujimiDesktop = false;
  await context.submitVoiceEditor({ preventDefault() {} });
  console.log(JSON.stringify({ desktop, writes }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'desktop': [],
            'writes': [
                {'path': '/api/settings/browser-voice',
                 'body': {'name': 'Microsoft Custom - Japanese (Japan)', 'label': '自定义'}},
                {'path': '/api/settings/browser-voice',
                 'body': {'name': 'Microsoft Custom - Japanese (Japan)', 'label': '自定义'}},
            ],
        })

    def test_example_voice_choices_use_actual_browser_name(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function browserVoiceShortName(');
const end = source.indexOf('async function populateRereadVoices(', start);
if (start < 0 || end < 0) throw new Error('Example voice choices were not found');
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
const keita = 'Microsoft Keita Online (Natural) - Japanese (Japan)';
const mode = { mode: 'browser', browser_voice_name: keita };
const voices = [{ id: 7, name: '浅倉透' }];
const legacy = context.exampleVoiceChoices(voices, mode, keita, 'inherit');
const saved = context.exampleVoiceChoices(voices, mode, keita, `browser:${encodeURIComponent('Haruka')}`);
const otherDevice = context.exampleVoiceChoices(voices, mode, 'Haruka', 'inherit');
console.log(JSON.stringify({ legacy, saved, otherDevice }));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        choices = json.loads(result.stdout)
        self.assertEqual(choices['legacy']['choice'], 'browser:Microsoft%20Keita%20Online%20(Natural)%20-%20Japanese%20(Japan)')
        self.assertEqual(choices['legacy']['options'], [
            {'label': '圭太', 'value': choices['legacy']['choice']},
            {'label': '浅倉透', 'value': 'voice:7'},
        ])
        self.assertEqual(choices['saved']['choice'], 'browser:Haruka')
        self.assertEqual(choices['saved']['options'][-1], {'label': 'Haruka', 'value': 'browser:Haruka'})
        self.assertEqual(choices['otherDevice']['options'][0], {'label': 'Haruka', 'value': 'browser:Haruka'})

    def test_browser_voice_editor_keeps_unavailable_saved_choice_visible(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('async function populateBrowserVoiceSelect()');
const end = source.indexOf('function openVoiceDialog(', start);
if (start < 0 || end < 0) throw new Error('Browser voice editor was not found');
const savedName = 'Microsoft Keita Online (Natural) - Japanese (Japan)';
const haruka = { name: 'Microsoft Haruka Desktop - Japanese', lang: 'ja-JP', default: true };
const select = {
  disabled: false,
  options: [],
  value: '',
  replaceChildren(...options) {
    this.options = options;
    this.value = options[0]?.value || '';
  },
};
const submit = { disabled: false };
const context = {
  $: selector => selector === '#browser-voice-select' ? select : submit,
  state: { editingBrowserVoice: true, browserVoiceName: savedName },
  waitForJapaneseBrowserVoice: async () => null,
  japaneseBrowserVoices: () => [haruka],
  desktopOnlineVoices: () => [],
  desktopOnlineVoice: () => null,
  isHiddenBrowserVoiceName: () => false,
  browserVoiceShortName: name => name.includes('Keita') ? '圭太' : 'Haruka',
  preferredJapaneseBrowserVoice: voices => voices[0],
  panelNotice: () => {},
  Option: class { constructor(label, value) { this.label = label; this.value = value; } },
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.populateBrowserVoiceSelect();
  console.log(JSON.stringify({ selected: select.value, label: select.options[0].label, saveDisabled: submit.disabled }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'selected': 'Microsoft Keita Online (Natural) - Japanese (Japan)',
            'label': '圭太（当前设备不可用）',
            'saveDisabled': True,
        })

    def test_browser_voice_editor_omits_removed_saved_choice(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function japaneseBrowserVoices()');
const end = source.indexOf('function openVoiceDialog(', start);
const haruka = { name: 'Microsoft Haruka - Japanese (Japan)', lang: 'ja-JP', default: true };
const nanami = { name: 'Microsoft Nanami - Japanese (Japan)', lang: 'ja-JP' };
const select = {
  options: [], value: '', disabled: false,
  replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; },
};
const submit = { disabled: false };
const context = {
  $: selector => selector === '#browser-voice-select' ? select : submit,
  window: { speechSynthesis: {} },
  speechSynthesis: { getVoices: () => [haruka, nanami] },
  state: { editingBrowserVoice: true, browserVoiceName: haruka.name },
  panelNotice: () => {},
  Option: class { constructor(label, value) { this.label = label; this.value = value; } },
  setInterval, clearInterval, setTimeout, clearTimeout,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.populateBrowserVoiceSelect();
  console.log(JSON.stringify({ options: select.options.map(option => option.value), selected: select.value, disabled: submit.disabled }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'options': ['Microsoft Nanami - Japanese (Japan)'],
            'selected': 'Microsoft Nanami - Japanese (Japan)',
            'disabled': False,
        })

    def test_saved_browser_voice_survives_delayed_voice_enumeration(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function japaneseBrowserVoices()');
const end = source.indexOf('function browserVoiceShortName(', start);
if (start < 0 || end < 0) throw new Error('Browser voice logic was not found');
const keita = { name: 'Microsoft Keita Online (Natural) - Japanese (Japan)', lang: 'ja-JP' };
const haruka = { name: 'Microsoft Haruka Desktop - Japanese', lang: 'ja-JP', default: true };
let voices = [haruka];
const writes = [];
const listeners = new Set();
const saved = { browser_voice_name: keita.name, browser_voice_label: 'ブラウザー' };
const context = {
  window: { speechSynthesis: {} },
  speechSynthesis: {
    getVoices: () => voices,
    addEventListener: (_, listener) => listeners.add(listener),
    removeEventListener: (_, listener) => listeners.delete(listener),
  },
  state: { browserVoiceName: '', browserVoiceLabel: 'ブラウザー' },
  api: async (path, options) => {
    if (options) { writes.push(JSON.parse(options.body)); return {}; }
    return saved;
  },
  setInterval, clearInterval, setTimeout, clearTimeout,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  const loading = context.initializeBrowserVoice();
  setTimeout(() => {
    voices = [haruka, keita];
    listeners.forEach(listener => listener());
  }, 20);
  await loading;
  console.log(JSON.stringify({ selected: context.state.browserVoiceName, writes }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'selected': 'Microsoft Keita Online (Natural) - Japanese (Japan)',
            'writes': [],
        })

    def test_browser_speech_timer_does_not_outrun_boundary_events(self):
        script = r'''
const { advanceBrowserSpeechIndex } = require('./static/browser-speech.js');
const withBoundary = { index: 10, textLength: 100, charactersPerSecond: 20, rate: 1, hasBoundaryEvents: true };
const withoutBoundary = { index: 10, textLength: 100, charactersPerSecond: 20, rate: 1, hasBoundaryEvents: false };
console.log(JSON.stringify([
  advanceBrowserSpeechIndex(withBoundary, 1),
  advanceBrowserSpeechIndex(withoutBoundary, 1),
]));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [10, 30])

    def test_voice_count_is_removed_from_voice_heading(self):
        page = BeautifulSoup((ROOT/'static/index.html').read_text(encoding='utf-8'), 'html.parser')
        self.assertIsNone(page.select_one('.voice-panel .voice-heading-meta'))
        self.assertIsNone(page.select_one('.voice-panel #voice-count'))

    def test_frontmatter_text_blocks_support_bookmarks(self):
        script = r'''
const { bookBlockSupportsBookmark, chapterProgressPercent, selectBookReadingPosition } = require('./static/book-reader.js');
console.log(JSON.stringify([
  bookBlockSupportsBookmark({is_frontmatter: true}, {kind: 'paragraph'}),
  bookBlockSupportsBookmark({is_frontmatter: true}, {kind: 'heading'}),
  bookBlockSupportsBookmark({is_frontmatter: true}, {kind: 'image'}),
  bookBlockSupportsBookmark({is_frontmatter: true}, {kind: 'spacer'}),
  chapterProgressPercent({block_count: 100}, 25),
  selectBookReadingPosition({chapters: [{id: 1}], progress: {chapter_id: 2, block_index: 8}, bookmarks: [{chapter_id: 1, block_index: 3}]}),
]));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [True, True, False, False, 26,
            {'chapterId': 1, 'blockIndex': 3, 'startAtBeginning': False}])


if __name__ == '__main__':
    unittest.main()
