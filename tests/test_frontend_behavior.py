import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendBehaviorTests(unittest.TestCase):
    def test_frontmatter_text_blocks_support_bookmarks(self):
        script = r'''
const { bookBlockSupportsBookmark } = require('./static/book-reader.js');
console.log(JSON.stringify([
  bookBlockSupportsBookmark({is_frontmatter: true}, {kind: 'paragraph'}),
  bookBlockSupportsBookmark({is_frontmatter: true}, {kind: 'heading'}),
  bookBlockSupportsBookmark({is_frontmatter: true}, {kind: 'image'}),
  bookBlockSupportsBookmark({is_frontmatter: true}, {kind: 'spacer'}),
]));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [True, True, False, False])


if __name__ == '__main__':
    unittest.main()
