import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendBrowserTTSTests(unittest.TestCase):
    def test_local_browser_reread_requests_saved_audio_for_selected_voice(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('async function rereadArticle(');
const end = source.indexOf('async function cancelReread(', start);
const requests = [];
const messages = [];
const context = {
  window: { FujimiDesktop: false }, state: { browserVoiceName: 'voicevox:8' },
  desktopOnlineVoice: () => null, setRereadTask: () => {}, stopRereadTracking: () => {},
  articleApiPath: (_article, path) => `/api/articles/7${path}`,
  api: async (path, options) => { requests.push([path, JSON.parse(options.body)]); return { status: 'ready', article: { id: 7, audio_path: '/audio/voice.wav' } }; },
  openArticle: article => { context.opened = article.audio_path; }, toast: message => messages.push(message),
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.rereadArticle({ id: 7 }, 'browser', {}, {});
  console.log(JSON.stringify({ requests, opened: context.opened, messages }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'requests': [['/api/articles/7/reread', {'mode': 'browser', 'voice_id': None,
                                                      'browser_voice_name': 'voicevox:8'}]],
            'opened': '/audio/voice.wav', 'messages': ['ブラウザー音声を保存しました。'],
        })

    def test_book_prefers_saved_browser_audio_over_live_speech(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function setupBookAudio(');
const end = source.indexOf('async function startBookTaskTracking(', start);
const audio = { src: '', addEventListener: () => {} };
const context = {
  $: () => audio, mobileMediaUrl: value => value,
  setupNativeArticlePlayer: () => { context.native = true; },
  setupBrowserArticlePlayer: () => { context.live = true; },
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
context.setupBookAudio({ book: { progress: {} }, chapter: { voice_mode: 'browser',
  blocks: [{ text_ja: '本文。' }], audio: { url: '/saved.wav', voice_id: null, voice_name: 'voicevox:8', segments: [] } } }, {});
console.log(JSON.stringify({ src: audio.src, native: !!context.native, live: !!context.live }));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {'src': '/saved.wav', 'native': True, 'live': False})

    def test_unavailable_local_catalog_is_not_shown_as_working(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('const LOCAL_BROWSER_VOICES =');
const end = source.indexOf('function japaneseBrowserVoices()', start);
const context = { state: { browserVoices: [] } };
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
console.log(JSON.stringify(context.localBrowserVoices()));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [])

    def test_import_voice_defaults_to_selected_local_voice(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function browserVoiceShortName(');
const end = source.indexOf('async function populateRereadVoices(', start);
const context = { localBrowserVoices: () => [{ id: 'voicevox:8', name: '春日部つむぎ', available: true }] };
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
const mode = { mode: 'browser', browser_voice_name: 'voicevox:8' };
console.log(JSON.stringify(context.exampleVoiceChoices([], mode, 'Microsoft Nanami Online', 'inherit')));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        choice = json.loads(result.stdout)
        self.assertEqual(choice['choice'], 'browser:voicevox%3A8')
        self.assertEqual(choice['options'][0]['value'], 'browser:voicevox%3A8')

    def test_browser_voice_editor_includes_local_catalog(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('async function populateBrowserVoiceSelect()');
const end = source.indexOf('function openVoiceDialog(', start);
const local = [
  { id: 'kokoro:jf_alpha', name: 'アルファ', available: true },
  { id: 'voicevox:8', name: '春日部つむぎ', available: true },
  { id: 'voicevox:109', name: '東北イタコ', available: true },
  { id: 'voicevox:107', name: '東北ずん子', available: true },
  { id: 'voicevox:16', name: '九州そら', available: true },
  { id: 'voicevox:69', name: '満別花丸', available: true },
  { id: 'voicevox:74', name: '琴詠ニア', available: true },
  { id: 'voicevox:89', name: 'Voidoll', available: true },
  { id: 'voicevox:47', name: 'ナースロボ＿タイプＴ', available: true },
];
const select = { options: [], value: '', disabled: false, replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; } };
const submit = { disabled: false };
const fields = { '#browser-voice-select': select, '#submit-voice': submit };
const context = {
  $: selector => fields[selector], Option: class { constructor(label, value) { this.label = label; this.value = value; this.disabled = false; } },
  state: { editingBrowserVoice: true, browserVoiceName: 'voicevox:8', browserVoiceLabel: '' },
  localBrowserVoices: () => local,
  api: async path => path === '/api/browser-voices' ? local : [],
  desktopOnlineVoice: () => null, desktopOnlineVoices: () => [],
  waitForJapaneseBrowserVoice: async () => null, japaneseBrowserVoices: () => [],
  preferredJapaneseBrowserVoice: () => null, isHiddenBrowserVoiceName: () => false,
  browserVoiceShortName: name => name,
  panelNotice: () => {},
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.populateBrowserVoiceSelect();
  console.log(JSON.stringify({ values: select.options.map(option => option.value), labels: select.options.map(option => option.label), selected: select.value, disabled: submit.disabled }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'values': ['kokoro:jf_alpha', 'voicevox:8', 'voicevox:109', 'voicevox:107', 'voicevox:16',
                       'voicevox:69', 'voicevox:74', 'voicevox:89', 'voicevox:47'],
            'labels': ['アルファ', '春日部つむぎ', '東北イタコ', '東北ずん子', '九州そら',
                       '満別花丸', '琴詠ニア', 'Voidoll', 'ナースロボ＿タイプＴ'],
            'selected': 'voicevox:8', 'disabled': False,
        })

    def test_local_browser_voice_catalog_is_exposed(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('const LOCAL_BROWSER_VOICES =');
const end = source.indexOf('function japaneseBrowserVoices()', start);
if (start < 0 || end < 0) { console.log('[]'); process.exit(0); }
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
console.log(JSON.stringify(context.localBrowserVoices().map(voice => [voice.id, voice.name])));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [
            ['kokoro:jf_alpha', 'アルファ'], ['voicevox:8', '春日部つむぎ'],
            ['voicevox:109', '東北イタコ'], ['voicevox:107', '東北ずん子'],
            ['voicevox:16', '九州そら'], ['voicevox:69', '満別花丸'],
            ['voicevox:74', '琴詠ニア'], ['voicevox:89', 'Voidoll'],
            ['voicevox:47', 'ナースロボ＿タイプＴ'],
        ])

    def test_local_browser_speech_chunk_uses_local_endpoint(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('./static/main.js', 'utf8');
const start = source.indexOf('function stopDesktopOnlineAudio(');
const end = source.indexOf('async function speakBrowserSpeech(', start);
const requests = [];
const audios = [];
const controller = { text: 'あ'.repeat(1300), index: 0, token: 1, rate: 1, cancelled: false, playing: true, started: true };
const context = {
  state: { browserSpeech: controller }, AbortController,
  synthesizeLocalBrowserSpeech: async (text, voice) => { requests.push([text.length, voice.id]); return {}; },
  URL: { createObjectURL: () => `blob:${audios.length}`, revokeObjectURL: () => {} },
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
  if (typeof context.speakLocalBrowserChunk !== 'function') {
    console.log(JSON.stringify({ missing: true }));
    return;
  }
  await context.speakLocalBrowserChunk(controller, { id: 'voicevox:8', local: true }, 1);
  audios[0].onended();
  await new Promise(resolve => setTimeout(resolve, 0));
  console.log(JSON.stringify({ requests, count: audios.length }));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            'requests': [[1200, 'voicevox:8'], [100, 'voicevox:8']],
            'count': 2,
        })


if __name__ == '__main__':
    unittest.main()
