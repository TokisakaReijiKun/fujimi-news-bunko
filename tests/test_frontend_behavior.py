import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendBehaviorTests(unittest.TestCase):
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
