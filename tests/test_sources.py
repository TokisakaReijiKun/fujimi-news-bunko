import unittest

from news_sources import default_sources, upgrade_sources, collect_source_links, yahoo_article_url


class SourcesTests(unittest.TestCase):
    def test_six_defaults_and_existing_settings_upgrade(self):
        sources = default_sources()
        self.assertEqual([s['name'] for s in sources], ['NHKニュース', '朝日新聞', '読売新聞', '日本経済新聞', '産経新聞', 'Yahoo!ニュース'])
        original = [dict(id=7, name='NHK', homepage='https://www.nhk.or.jp/rss/news/cat0.xml', minimum_count=3, voice_mode='none'),
                    dict(id=12, name='Personal', homepage='https://example.com/rss', minimum_count=0)]
        upgraded = upgrade_sources(original)
        self.assertEqual(len(upgraded), 7)
        self.assertEqual(len({s['id'] for s in upgraded}), 7)
        self.assertEqual(upgraded[0]['id'], 7)
        self.assertEqual(upgraded[0]['minimum_count'], 3)
        self.assertEqual(upgraded[0]['voice_mode'], 'none')
        self.assertEqual(upgraded[0]['homepage'], 'https://news.web.nhk/newsweb/')
        self.assertEqual(upgraded[1], original[1])
        self.assertEqual(upgrade_sources(upgraded), upgraded)
        self.assertEqual(original[0]['name'], 'NHK')

    def test_each_official_homepage_accepts_article_links_and_deduplicates(self):
        paths = ['/newsweb/na/nd-20260907de48714', '/articles/ASV9731JTV97ULFA015M.html',
                 '/national/20260907-GYT1T00281/', '/article/DGXZQOUB078230X00C26A9000000/',
                 '/article/20260907-ZHDHLSYIE5J2JFP5NW6VB5XQ34/', '/pickup/6594575']
        for source, path in zip(default_sources(), paths):
            blob = f'<html><a href="{path}?iref=top">Headline</a><a href="{path}#duplicate">Again</a><a href="https://example.com{path}">Other domain</a><a href="/settings/">Navigation</a></html>'.encode()
            links = collect_source_links(source, lambda _: (blob, source['homepage']))
            self.assertEqual(len(links), 1, source['name'])
            self.assertTrue(links[0].endswith(path), links)

    def test_rss_atom_rdf_and_yahoo_full_article(self):
        documents = [
            b'<rss><channel><item><link>https://example.com/article/a</link></item></channel></rss>',
            b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><link href="/article/a"/></entry></feed>',
            b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"><item><link>https://example.com/article/a</link></item></rdf:RDF>']
        for blob in documents:
            self.assertEqual(collect_source_links({'homepage':'https://example.com/feed'}, lambda _: (blob,'https://example.com/feed')), ['https://example.com/article/a'])
        url = 'https://news.yahoo.co.jp/articles/' + 'a' * 40
        blob = f'<a href="{url}">記事全文を読む</a>'.encode()
        self.assertEqual(yahoo_article_url(blob, 'https://news.yahoo.co.jp/pickup/123'), url)
        self.assertIsNone(yahoo_article_url(blob, url))
        with self.assertRaises(ValueError):
            yahoo_article_url(b'<p>No article</p>', 'https://news.yahoo.co.jp/pickup/123')


if __name__ == '__main__':
    unittest.main()
