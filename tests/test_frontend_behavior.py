import json
from pathlib import Path
import subprocess
import unittest
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]


class FrontendBehaviorTests(unittest.TestCase):
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
