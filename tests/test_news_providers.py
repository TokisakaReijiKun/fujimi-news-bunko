"""Nikkei company-list exclusions stay local to that publisher."""
import unittest

from article_extraction import ArticleExtractionError, fetch_article
from news_providers import nikkei, yomiuri


URL = 'https://www.nikkei.com/article/DGXZQODL160R40W6A011C2000000/'
OTHER_URL = 'https://www.nikkei.com/article/DGXZQODL170R40W6A011C2000000/'


def article_html(title):
    return f'<main id="main-content"><article><h1>{title}</h1><div data-track-article-content><p class="paragraph_test">企業が新しいサービスを発表しました。</p></div></article></main>'.encode('utf-8')


class NikkeiCompanyListTests(unittest.TestCase):
    def test_listing_excludes_company_list_and_duplicate_thumbnail_links(self):
        html = f'<a href="{URL}?ref=top"><span>【企業一覧】</span>個人情報の漏洩</a><a href="{URL}"><img src="photo.jpg"></a><a href="{OTHER_URL}">企業が新サービスを発表</a>'
        self.assertEqual(nikkei.html_links(html, 'https://www.nikkei.com/'), [OTHER_URL])

    def test_direct_import_rejects_company_list_before_body_or_media_parsing(self):
        html = article_html('【企業一覧】 個人情報の漏洩・恐れを公表した企業など')
        with self.assertRaisesRegex(ArticleExtractionError, '企業一覧'):
            fetch_article(URL, lambda url, **kwargs: (html, url))

    def test_regular_company_news_is_preserved(self):
        result = nikkei.extract_page(article_html('企業が新しいサービスを発表'), URL)
        self.assertEqual(result['paragraphs'], ['企業が新しいサービスを発表しました。'])

    def test_other_source_does_not_inherit_nikkei_title_exclusion(self):
        url = 'https://www.yomiuri.co.jp/economy/20261031-OYT1T50001/'
        self.assertEqual(yomiuri.html_links(f'<a href="{url}">【企業一覧】企業のニュース</a>', url), [url])


if __name__ == '__main__':
    unittest.main()
