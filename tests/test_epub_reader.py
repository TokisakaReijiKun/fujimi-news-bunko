import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from bs4 import BeautifulSoup
from epub_parser import parse_epub, anchor_id
from book_store import BookStore, source_epub_name
from article_store import db_connection, digest


def epub3(ncx=False):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('mimetype','application/epub+zip')
        z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        nav_item='<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>' if not ncx else '<item id="nav" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        z.writestr('OPS/book.opf','''<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>  真实书名  </dc:title><dc:creator> 作者 </dc:creator></metadata><manifest>'''+nav_item+'''<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/><item id="image" href="Images/a.png" media-type="image/png" properties="cover-image"/></manifest><spine toc="nav"><itemref idref="cover"/><itemref idref="a"/><itemref idref="b"/><itemref idref="c"/></spine></package>''')
        z.writestr('OPS/nav.xhtml','''<html><body><nav epub:type="toc"><ol><li><a href="a.xhtml#one">第一章</a><ol><li><a href="b.xhtml#sub">小节</a></li></ol></li><li><a href="c.xhtml">第二章</a></li></ol></nav></body></html>''')
        z.writestr('OPS/toc.ncx','''<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap><navPoint><navLabel><text>第一章</text></navLabel><content src="a.xhtml#one"/><navPoint><navLabel><text>小节</text></navLabel><content src="b.xhtml#sub"/></navPoint></navPoint><navPoint><navLabel><text>第二章</text></navLabel><content src="c.xhtml"/></navPoint></navMap></ncx>''')
        z.writestr('OPS/cover.xhtml','<html><body><div><svg><image xlink:href="Images/a.png"/></svg></div></body></html>')
        z.writestr('OPS/a.xhtml','''<html><head><title>所有文件相同书名</title></head><body><p id="one"><a href="b.xhtml#sub"><img src="Images/a.png"/></a></p><p>中文段落。</p><p style="opacity:0.4;">日本語の<ruby><rb>文</rb><rt>ぶん</rt></ruby>です。</p><p>天地玄黄。</p><script>alert(1)</script></body></html>''')
        z.writestr('OPS/b.xhtml','<html><body><div id="sub"><p>続きの本文です。</p><p><img src="Images/a.png"/></p></div></body></html>')
        z.writestr('OPS/c.xhtml','<html><body><h1>第二章</h1><p style="text-align:center;position:fixed;background:url(https://evil)">終わり。</p><a href="javascript:alert(1)">無効リンク</a></body></html>')
        z.writestr('OPS/Images/a.png',b'image-test')
    return stream.getvalue()


class EpubReaderTests(unittest.TestCase):
    def test_original_epub_filename_is_preserved_and_sanitized(self):
        original='zh-jp.Ysgy.[八目迷] きのうの春で、君を待つ.epub'
        self.assertEqual(source_epub_name(original),original)
        self.assertEqual(source_epub_name(r'C:\unsafe\CON?.epub'),'CON_.epub')
        self.assertNotIn('/',source_epub_name('../unsafe/name.epub'))

    def test_official_nav_ncx_spine_grouping_and_pairing(self):
        for ncx in (False,True):
            b,assets=parse_epub(epub3(ncx),'test.epub')
            self.assertEqual(b['title'],'真实书名');self.assertEqual(b['author'],'作者')
            self.assertEqual([e['title'] for e in b['toc']],['第一章','小节','第二章'])
            self.assertEqual([e['depth'] for e in b['toc']],[0,1,0])
            self.assertEqual(len(b['chapters']),3) # cover + two logical chapters
            self.assertEqual(b['chapters'][0]['title'],'Chapter1')
            self.assertTrue(b['chapters'][0]['is_frontmatter'])
            self.assertEqual(b['chapters'][0]['blocks'][0]['kind'],'image')
            self.assertFalse(b['chapters'][1]['is_frontmatter'])
            self.assertEqual(b['chapters'][1]['source_hrefs'],['OPS/a.xhtml','OPS/b.xhtml'])
            blocks=b['chapters'][1]['blocks']
            pair=next(x for x in blocks if x['bilingual_pair'])
            self.assertEqual(pair['text_ja'],'日本語の文です。');self.assertEqual(pair['text_zh'],'中文段落。')
            self.assertTrue(any(x['text_ja']=='天地玄黄。' for x in blocks))
            self.assertEqual(sum(x['kind']=='image' for ch in b['chapters'] for x in ch['blocks']),3)
            target=b['toc'][1]
            self.assertEqual(target['chapter_id'],2)
            self.assertIn(target['anchor'],blocks[target['block_index']]['anchor_ids'])
            markup=''.join(x['html'] for ch in b['chapters'] for x in ch['blocks'])
            self.assertNotIn('<script',markup);self.assertNotIn('javascript:',markup);self.assertNotIn('position:fixed',markup)
            self.assertIn('text-align:center',markup);self.assertIn('data-book-href',markup);self.assertIn('<ruby>',markup)
            self.assertIn('OPS/Images/a.png',assets)

    def test_archive_traversal_rejected(self):
        out=io.BytesIO(epub3())
        with zipfile.ZipFile(out,'a') as z:z.writestr('../outside.txt','bad')
        with self.assertRaises(ValueError):parse_epub(out.getvalue(),'bad.epub')

    def test_book_files_source_and_state_independent_of_chapter_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            store=BookStore(directory);blob=epub3();b,assets=parse_epub(blob,'test.epub')
            bid,duplicate=store.create(b,blob,assets);self.assertFalse(duplicate)
            folder=store.folder(bid)
            self.assertEqual((folder/'test.epub').read_bytes(),blob)
            self.assertEqual(sorted(p.name for p in folder.iterdir()),['audio','book.json','chapters','resources','state.json','test.epub'])
            manifest=json.loads((folder/'book.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['source_file'],'test.epub')
            self.assertEqual(manifest['source_sha256'],digest(blob))
            chapter=folder/'chapters/0002.json';before=chapter.stat().st_mtime_ns
            store.patch_state(bid,{'progress':{'chapter_id':2,'block_index':2},'bookmarks':[{'chapter_id':2,'block_index':2}]})
            self.assertEqual(chapter.stat().st_mtime_ns,before)
            loaded=store.load(bid);self.assertEqual(loaded['progress']['chapter_id'],2)
            self.assertEqual(store.create(b,blob,assets),(bid,True))
            loaded['title']='修改书名';store.save(loaded)
            self.assertEqual(store.folder(bid),folder)
            with db_connection(store.db) as db:
                self.assertNotIn('payload',{r['name'] for r in db.execute('PRAGMA table_info(books)')})
                db.execute('DELETE FROM books')
            store.refresh();self.assertEqual(store.load(bid)['title'],'修改书名')
            with self.assertRaises(LookupError):store.asset(bid,'../../.env')
            self.assertEqual(store.asset(bid,'OPS/Images/a.png').read_bytes(),b'image-test')

    def test_interrupted_book_commit_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            store=BookStore(directory);b,assets=parse_epub(epub3(),'test.epub');bid,_=store.create(b,epub3(),assets)
            b=store.load(bid);b['title']='after recovery'
            with patch.object(store,'_index',side_effect=RuntimeError('index unavailable')):
                with self.assertRaises(RuntimeError):store.save(b)
            recovered=BookStore(directory)
            self.assertEqual(recovered.load(bid)['title'],'after recovery')
