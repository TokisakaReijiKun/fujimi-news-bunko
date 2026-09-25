import json
from pathlib import Path
import subprocess
import unittest
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]


class FrontendBehaviorTests(unittest.TestCase):
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

    def test_voice_count_is_beside_the_voice_description(self):
        page = BeautifulSoup((ROOT/'static/index.html').read_text(encoding='utf-8'), 'html.parser')
        meta = page.select_one('.voice-panel .voice-heading-meta')
        self.assertIsNotNone(meta)
        self.assertEqual(meta.select_one(':scope > p').get_text(strip=True),
                         '管理首次朗读与読み返し使用的参考声线。')
        self.assertIsNotNone(meta.select_one(':scope > .voice-overview > #voice-count'))
        self.assertIsNone(page.select_one('.voice-panel > .voice-overview'))

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
