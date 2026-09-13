"""Regressions from the publishers' observed September listing structures."""
import json
import tempfile
import unittest
from unittest.mock import patch, Mock

import requests
from article_store import db_connection
from news_providers import asahi, nikkei, nhk
from news_providers.primitives import PaidArticleError, ArticleExtractionError
from server import create_app, download, WORK_CONTEXT, WorkCancelled
from tests.test_news_providers import URLS, page


class SourceRegressionTests(unittest.TestCase):
    def test_download_retries_transient_http_without_ignoring_final_error(self):
        def response(status):
            r = Mock(status_code=status, is_redirect=False)
            r.__enter__ = Mock(return_value=r); r.__exit__ = Mock(return_value=False)
            r.iter_content.return_value = [b'public']
            if status != 200: r.raise_for_status.side_effect = requests.HTTPError(response=r)
            return r
        denied, good = response(403), response(200)
        with patch('server.public_url'), patch('server.time.sleep'), patch('server.requests.get', side_effect=[denied, good]) as get:
            self.assertEqual(download('https://example.com/'), (b'public', 'https://example.com/'))
            denied.close.assert_called_once()
            self.assertEqual(get.call_count, 2)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertNotIn('verify', get.call_args.kwargs)
        denied = response(403)
        with patch('server.public_url'), patch('server.time.sleep'), patch('server.requests.get', return_value=denied) as get:
            with self.assertRaises(requests.HTTPError): download('https://example.com/')
            self.assertEqual(get.call_count, 3)

    def test_download_redirect_and_body_limits_still_apply(self):
        r=Mock(status_code=302,is_redirect=True,headers={'Location':'http://127.0.0.1/'})
        r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
        with patch('server.public_url',side_effect=[None,ValueError('private')]), patch('server.requests.get',return_value=r) as get:
            with self.assertRaises(ValueError): download('https://example.com/')
            get.assert_called_once()
        r.status_code=200;r.is_redirect=False;r.iter_content.return_value=[b'1234']
        with patch('server.public_url'), patch('server.requests.get',return_value=r):
            with self.assertRaises(ValueError): download('https://example.com/',max_bytes=3)

    def test_sibling_image_lock_rejects_all_duplicate_links_but_not_free_card(self):
        for module in (asahi, nikkei):
            paid = URLS[module.KEY]
            free = paid.replace('TEST', 'FREE')
            label = '有料記事' if module is asahi else '有料会員限定記事'
            markup = (f'<a href="{paid}">duplicate without badge</a>'
                      f'<article><a href="{paid}">overlay</a><h2><a href="{paid}?ref=x">title</a>'
                      f'<span><img alt="{label}" src="/lock.svg"></span></h2></article>'
                      f'<article data-paywall="false"><h2><a href="{free}">public</a></h2></article>')
            self.assertEqual(module.html_links(markup, paid), [free])

    def nikkei_page(self, **changes):
        props = {'kijiId': 'DGXTEST', 'isLockedArticle': False, 'isPaidUserOnlyArticle': False,
                 'lockStatus': {'type': 'anonymous', 'isLocked': False, 'isDynamicLocked': False}}
        props.update(changes)
        context = '<script id="js-k2-hydrate-client-exposed-context" type="application/json">' + json.dumps({'paywallProps': props}) + '</script>'
        return page('nikkei').decode().replace('</body>', context + '</body>').replace(
            '</main>', '<div class="mainPaywall_mw73lue"><p>すべての記事が読み放題 有料会員が初回1カ月無料</p></div></main>')

    def test_nikkei_free_anonymous_article_ad_is_not_a_gate(self):
        self.assertEqual(nikkei.extract_page(self.nikkei_page(), URLS['nikkei'])['paragraphs'], ['第一段。', '第二段。'])

    def test_nikkei_conflicting_or_other_article_unlock_does_not_override_gate(self):
        for changes in ({'kijiId': 'OTHER'}, {'isPaidUserOnlyArticle': True},
                        {'lockStatus': {'type': 'subscriber', 'isLocked': False, 'isDynamicLocked': False}},
                        {'isLockedArticle': True}):
            with self.assertRaises(PaidArticleError):
                nikkei.extract_page(self.nikkei_page(**changes), URLS['nikkei'])
        for extra in ('<p>この記事は会員限定です。</p>',
                      '<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script>'):
            with self.assertRaises(PaidArticleError):
                nikkei.extract_page(self.nikkei_page().replace('</main>', extra + '</main>'), URLS['nikkei'])

    def test_asahi_teaser_and_real_membership_notice_is_rejected(self):
        blob = '<h1>Test</h1><div class="ArticleText"><p>公開の要約です。</p><p>この記事は有料会員限定です。</p></div>'
        with self.assertRaises(PaidArticleError):
            asahi.extract_page(blob, URLS['asahi'])

    def test_nhk_feed_uses_https_and_refuses_expired_fallback(self):
        url = 'http://www3.nhk.or.jp/news/html/20200101/k100000000.html'
        feed = f'<rss><channel><item><link>{url}</link><pubDate>Wed, 01 Jan 2020 00:00:00 GMT</pubDate></item></channel></rss>'
        self.assertEqual(nhk.html_links(feed, nhk.OFFICIAL_RSS), [url.replace('http:', 'https:')])
        response = requests.Response(); response.status_code = 403
        with self.assertRaises(ArticleExtractionError):
            nhk.collect({'homepage': 'https://news.web.nhk/newsweb/'},
                        unittest.mock.Mock(side_effect=[requests.HTTPError(response=response), (feed, nhk.OFFICIAL_RSS)]))

    def test_restart_preserves_failure_diagnostics_despite_new_target(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder)
            task = {'status': 'partial', 'stage': 'partial', 'total': 13, 'completed': 11,
                    'pipeline_version': 5, 'errors': ['朝日新聞 HTTP 403'], 'message': 'evidence'}
            with db_connection(app.article_store.db_path) as db:
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('daily-result', json.dumps(task)))
            self.assertEqual(create_app(folder).test_client().get('/api/tasks/daily').json, task)
