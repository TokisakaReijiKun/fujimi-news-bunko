"""Publisher ownership, source-specific parsing and all write entry points."""
from copy import deepcopy
from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import requests
from article_extraction import extract_page, fetch_article
from article_store import db_connection
from news_providers import PROVIDERS, provider_for, custom, nhk, asahi, yomiuri, nikkei, sankei, yahoo
from news_providers.primitives import ArticleExtractionError, PaidArticleError
from news_sources import collect_source_links
from server import create_app, WORK_CONTEXT, WorkCancelled


URLS = {
    'nhk':'https://news.web.nhk/newsweb/na/nd-20260909test',
    'asahi':'https://www.asahi.com/articles/ASV900TEST.html',
    'yomiuri':'https://www.yomiuri.co.jp/world/20260909-GYT1T00001/',
    'nikkei':'https://www.nikkei.com/article/DGXTEST/',
    'sankei':'https://www.sankei.com/article/20260909-TEST/',
    'yahoo':'https://news.yahoo.co.jp/articles/'+'f'*40,
}
IMAGE='https://example.com/newsatcl/photo.png'


def page(key):
    paragraph='<p>第一段。</p><p>第二段。</p>'
    figure=f'<figure class="article-image"><img src="{IMAGE}"><figcaption>写真説明</figcaption></figure>'
    if key=='nhk':
        content=f'<main><div class="article-body">{paragraph}{figure}</div><aside><p>推薦</p><img src="/unrelated.jpg"></aside></main>'
    elif key=='asahi': content=f'<main><div class="ArticleText">{paragraph}{figure}</div><p>登録案内</p></main>'
    elif key=='yomiuri': content=f'<article class="article-content"><p>記事をシェアする</p><div class="p-main-contents">{paragraph.replace("<p>","<p itemprop=articleBody>")}{figure}</div><p>完了しました</p></article>'
    elif key=='nikkei': content=f'<main id="main-content"><article>{paragraph.replace("<p>","<p class=paragraph_a>")}{figure}<aside>有料会員募集中</aside></article></main>'
    elif key=='sankei': content=f'<article class="article-wrapper free"><div class="article-body">{paragraph.replace("<p>","<p class=article-text>")}{figure}</div><article class="storycard"><img src="/not-story.jpg"></article></article>'
    else: content=f'<article id="uamods"><header><h1>Yahoo heading</h1><p>配信時刻</p></header><div class="article_body"><p>署名</p><p class="yjSlinkDirectlink">第一段。\n\n第二段。</p>{figure}</div><p>関連記事</p></article>'
    return f'<html><head><title>Title</title></head><body><h1>Headline</h1>{content}</body></html>'.encode()


class ProviderParsingTests(unittest.TestCase):
    def test_six_owners_have_their_own_entrypoints(self):
        for module in PROVIDERS:
            for name in ('collect','extract_page','fetch_article','postprocess','retranslate'):
                self.assertEqual(getattr(module,name).__module__,module.__name__)
            self.assertIs(provider_for(URLS[module.KEY]),module)
        self.assertIs(provider_for('https://news.web.nhk.evil.example/'),custom)
        self.assertIs(provider_for('https://example.com/?source=nikkei.com'),custom)

    def test_each_source_extracts_only_its_body_and_media(self):
        for module in PROVIDERS:
            result=extract_page(page(module.KEY),URLS[module.KEY])
            self.assertEqual(result['source_key'],module.KEY)
            self.assertEqual(result['paragraphs'],['第一段。','第二段。'],module.KEY)
            self.assertEqual(len(result['images']),1,module.KEY)
            self.assertEqual(result['images'][0]['caption'],'写真説明')
        self.assertEqual(extract_page(page('yahoo'),URLS['yahoo'])['title'],'Yahoo heading')

    def test_asahi_current_main_layout_keeps_public_body_and_drops_subscription_copy(self):
        blob = ('<html><head><meta charset="utf-8"><title>Current Asahi</title>'
                '<script type="application/ld+json">{"@type":"NewsArticle","headline":"Current Asahi"}</script>'
                '</head><body><main id="main"><p>作者信息</p><div class="nfyQp">'
                '<p>\u516c\u958b\u672c\u6587\u7b2c\u4e00\u6bb5\u3002</p><p>\u516c\u958b\u672c\u6587\u7b2c\u4e8c\u6bb5\u3002</p>'
                '</div><p>\u6709\u6599\u4f1a\u54e1\u306b\u306a\u308b\u3068\u4f1a\u54e1\u9650\u5b9a\u306e\u6709\u6599\u8a18\u4e8b\u3082\u304a\u8aad\u307f\u3044\u305f\u3060\u3051\u307e\u3059\u3002</p>'
                '<p>\u3010\u3053\u306e\u8a18\u4e8b\u306e\u7d9a\u304d\u304c\u8aad\u3081\u308b\u3011</p>'
                '</main></body></html>').encode()
        result=asahi.extract_page(blob,URLS['asahi'])
        self.assertEqual(result['paragraphs'],['\u516c\u958b\u672c\u6587\u7b2c\u4e00\u6bb5\u3002','\u516c\u958b\u672c\u6587\u7b2c\u4e8c\u6bb5\u3002'])

    def test_asahi_subscription_copy_without_public_paragraphs_is_paid(self):
        blob = ('<html><head><script type="application/ld+json">{"@type":"NewsArticle","headline":"Paid"}</script></head>'
                '<body><main id="main"><div class="nfyQp"><p>\u6709\u6599\u4f1a\u54e1\u306b\u306a\u308b\u3068\u4f1a\u54e1\u9650\u5b9a\u306e\u6709\u6599\u8a18\u4e8b\u3082\u304a\u8aad\u307f\u3044\u305f\u3060\u3051\u307e\u3059\u3002</p>'
                '</div></main></body></html>').encode()
        with self.assertRaises(PaidArticleError):
            asahi.extract_page(blob,URLS['asahi'])

    def test_known_publisher_never_falls_back_to_custom(self):
        with patch.object(custom,'extract_page',side_effect=AssertionError('fallback forbidden')):
            for key in ('asahi','yomiuri','nikkei','sankei','yahoo'):
                with self.assertRaises(ArticleExtractionError):
                    extract_page(b'<html><h1>Generic</h1><main><p>Not the article body</p></main></html>',URLS[key])
        with patch.object(asahi,'extract_page',side_effect=ValueError('asahi broke')):
            self.assertEqual(extract_page(page('sankei'),URLS['sankei'])['source_key'],'sankei')

    def test_collectors_dispatch_independently_and_reject_foreign_articles(self):
        for module in PROVIDERS:
            homepages = {
                'nhk': 'https://news.web.nhk/newsweb/', 'asahi': 'https://www.asahi.com/',
                'yomiuri': 'https://www.yomiuri.co.jp/', 'nikkei': 'https://www.nikkei.com/',
                'sankei': 'https://www.sankei.com/', 'yahoo': 'https://news.yahoo.co.jp/',
            }
            source={'homepage':homepages[module.KEY], 'minimum_count':1}
            blob=f'<html><a href="{URLS[module.KEY]}">article</a><a href="https://evil.example/article/TEST/">foreign</a></html>'.encode()
            with patch.object(module,'collect',wraps=module.collect) as collect:
                def fetch(url):
                    return (blob, source['homepage']) if url == source['homepage'] else (page(module.KEY), url)
                self.assertEqual(collect_source_links(source,fetch),[URLS[module.KEY]])
                collect.assert_called_once()
            other=URLS['sankei'] if module is not sankei else URLS['asahi']
            with self.assertRaises(ArticleExtractionError):fetch_article(URLS[module.KEY],lambda _: (page(module.KEY),other))

    def test_listing_collectors_drop_visibly_member_only_cards(self):
        paid_urls = {
            'asahi': 'https://www.asahi.com/articles/ASV900SECOND.html',
            'yomiuri': 'https://www.yomiuri.co.jp/world/20260909-GYT1T00002/',
            'nikkei': 'https://www.nikkei.com/article/DGXSECOND/',
            'sankei': 'https://www.sankei.com/article/20260909-SECOND/',
        }
        for module in (asahi, yomiuri, nikkei, sankei):
            listing = (
                f'<article><a href="{URLS[module.KEY]}">公開記事</a></article>'
                f'<article class="premium">会員限定<a href="{paid_urls[module.KEY]}">会員記事</a></article>'
            ).encode()
            self.assertEqual(module.html_links(listing, URLS[module.KEY]), [URLS[module.KEY]], module.KEY)

    def test_asahi_and_nikkei_membership_is_decided_from_listing_cards(self):
        paid_urls = {
            'asahi': 'https://www.asahi.com/articles/ASV900PAID.html',
            'nikkei': 'https://www.nikkei.com/article/DGXPAID/',
        }
        for module in (asahi, nikkei):
            listing = (
                f'<div class="story-card premium">会員限定<a href="{paid_urls[module.KEY]}">paid</a></div>'
                f'<div class="story-card"><a href="{URLS[module.KEY]}">public</a></div>'
            ).encode()
            with patch.object(module, 'fetch_article') as extract:
                result = module.collect({'homepage': f'https://www.{module.KEY}.com/'},
                                        lambda _: (listing, f'https://www.{module.KEY}.com/'))
            self.assertEqual(result, [URLS[module.KEY]], module.KEY)
            extract.assert_not_called()

    def test_nhk_uses_its_official_rss_when_homepage_returns_403(self):
        response=requests.Response(); response.status_code=403
        denied=requests.HTTPError(response=response)
        feed=(f'<rss><channel><item><link>{URLS["nhk"]}</link></item></channel></rss>').encode()
        calls=[]
        def fetch(url, **kwargs):
            calls.append(url)
            if url == 'https://news.web.nhk/newsweb/':
                raise denied
            self.assertEqual(url,nhk.OFFICIAL_RSS)
            return feed,url
        result=nhk.collect({'homepage':'https://news.web.nhk/newsweb/'},fetch)
        self.assertEqual(result,[URLS['nhk']])
        self.assertEqual(calls,['https://news.web.nhk/newsweb/',nhk.OFFICIAL_RSS])

    def test_postprocessing_order_owned_by_the_source(self):
        class Services:
            def __init__(self):self.calls=[]
            def prepare(self,a,e,key):self.calls.append('prepare:'+key);return a
            def annotate(self,a):self.calls.append('annotate')
            def save(self,a):self.calls.append('save');return a
            def media(self,a,e,seconds):self.calls.append('media');return a
            def translate(self,a,seconds):self.calls.append('translate')
        for module in PROVIDERS:
            services=Services();module.postprocess({}, {},services)
            if module in (nhk,sankei):self.assertLess(services.calls.index('media'),services.calls.index('translate'))
            else:self.assertLess(services.calls.index('translate'),services.calls.index('media'))


class ProviderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.app=create_app(cls.temp.name);cls.client=cls.app.test_client()
        output=io.BytesIO();Image.new('RGB',(32,24),'blue').save(output,'PNG');cls.image=output.getvalue()

    @classmethod
    def tearDownClass(cls):
        WORK_CONTEXT.job=None;WORK_CONTEXT.deadline=None
        import gc
        gc.collect();cls.temp.cleanup()

    def fetch(self,url,**kwargs):
        if url==IMAGE:return self.image,url
        key=next(key for key,value in URLS.items() if value==url)
        return page(key),url

    def wait_task(self,url):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            result=self.client.get(url).json
            if result['status'] in ('completed','failed','cancelled'):return result
            time.sleep(.02)
        self.fail('task timeout')

    def test_daily_uses_all_six_collectors_and_postprocessors(self):
        sources=[{'id':i,'name':module.NAME,'homepage':URLS[module.KEY],'minimum_count':1} for i,module in enumerate(PROVIDERS,1)]
        with db_connection(self.app.article_store.db_path) as db:
            old_sources=db.execute("SELECT value FROM settings WHERE key='news-sources'").fetchone()[0]
            old_content=db.execute("SELECT value FROM settings WHERE key='daily-content'").fetchone()[0]
            db.execute("UPDATE settings SET value=? WHERE key='news-sources'",(json.dumps(sources),))
            db.execute("UPDATE settings SET value=? WHERE key='daily-content'",('{"target_count":6}',))
        try:
            with ExitStack() as stack:
                stack.enter_context(patch('server.download',side_effect=self.fetch))
                stack.enter_context(patch.dict('os.environ',{},clear=True))
                collectors=[stack.enter_context(patch.object(m,'collect',return_value=[URLS[m.KEY]])) for m in PROVIDERS]
                processors=[stack.enter_context(patch.object(m,'postprocess',wraps=m.postprocess)) for m in PROVIDERS]
                self.client.post('/api/daily/generate')
                task=self.wait_task('/api/tasks/daily')
                self.assertEqual(task['status'],'completed',task)
                self.assertEqual(task['completed'],6)
                self.assertEqual(task['missing_sources'],[])
                for mock in collectors+processors:mock.assert_called_once()
        finally:
            with db_connection(self.app.article_store.db_path) as db:
                db.execute("UPDATE settings SET value=? WHERE key='news-sources'",(old_sources,))
                db.execute("UPDATE settings SET value=? WHERE key='daily-content'",(old_content,))

    def test_import_repair_and_retranslate_use_each_source_module(self):
        with patch('server.download',side_effect=self.fetch),patch('server.public_url'),patch.dict('os.environ',{'DEEPSEEK_API_KEY':'test-only'},clear=True),patch('server.translate',side_effect=lambda text:['译：'+p for p in text]):
            for module in PROVIDERS:
                with patch.object(module,'postprocess',wraps=module.postprocess) as post:
                    response=self.client.post('/api/import/tasks',json={'url':URLS[module.KEY]})
                    task=self.wait_task('/api/import/tasks/'+response.json['task_id'])
                    self.assertEqual(task['status'],'completed',task)
                    post.assert_called_once()
                article=task['article'];aid=article['id']
                self.assertEqual(article['source_key'],module.KEY)
                self.assertEqual(article['translated_paragraphs'],['译：第一段。','译：第二段。'])
                self.assertEqual(len(article['image_paths']),1)
                with self.client.get(article['image_paths'][0]) as image_response:self.assertEqual(image_response.data,self.image)
                self.assertNotIn('_revision',article)
                with patch.object(module,'postprocess',wraps=module.postprocess) as repair:
                    fixed=self.app.fujimi_repair_article(aid);self.assertEqual(fixed['id'],aid);repair.assert_called_once()
                with patch.object(module,'retranslate',wraps=module.retranslate) as again:
                    response=self.client.post(f'/api/articles/{aid}/retranslate')
                    task=self.wait_task(f'/api/articles/{aid}/translation-task')
                    self.assertEqual(task['status'],'completed',task);again.assert_called_once()

    def test_member_article_never_enters_any_postprocessor(self):
        with patch('server.public_url'),patch.object(nikkei,'postprocess') as post:
            blob=page('nikkei').replace(b'</article>', '<div class="mainPaywall_hash">この記事は会員限定です。</div></article>'.encode(),1)
            with patch('server.download',return_value=(blob,URLS['nikkei'])):
                response=self.client.post('/api/import/tasks',json={'url':URLS['nikkei']})
                task=self.wait_task('/api/import/tasks/'+response.json['task_id'])
                self.assertEqual(task['status'],'failed');post.assert_not_called()

    def test_retranslation_failure_preserves_previous_translation(self):
        with patch('server.download',side_effect=self.fetch),patch('server.public_url'),patch.dict('os.environ',{'DEEPSEEK_API_KEY':'test-only'},clear=True),patch('server.translate',side_effect=lambda text:['已有译文']*len(text)):
            response=self.client.post('/api/import/tasks',json={'url':URLS['sankei']})
            task=self.wait_task('/api/import/tasks/'+response.json['task_id'])
            self.assertEqual(task['status'],'completed',task)
            aid=task['article']['id']
            before=self.client.get(f'/api/articles/{aid}').json['translated_paragraphs']
            with patch('server.translate',side_effect=TimeoutError('test service timeout')):
                self.client.post(f'/api/articles/{aid}/retranslate')
                task=self.wait_task(f'/api/articles/{aid}/translation-task')
                self.assertEqual(task['status'],'failed',task)
            current=self.client.get(f'/api/articles/{aid}').json
            self.assertEqual(current['translated_paragraphs'],before)
            self.assertIn('test service timeout',current['failure_reason'])

    def test_yahoo_broken_second_page_never_reaches_storage(self):
        url='https://news.yahoo.co.jp/articles/'+'e'*40
        first=page('yahoo').replace(b'</article>',f'<a href="{url}?page=2">次へ</a></article>'.encode())
        def fetch(requested,**kwargs):
            return (first,url) if '?' not in requested else (b'<h1>cache</h1>','https://news.yahoo.co.jp/cached-pages/20260909')
        with patch('server.public_url'),patch('server.download',side_effect=fetch),patch.object(yahoo,'postprocess') as post:
            response=self.client.post('/api/import/tasks',json={'url':url})
            task=self.wait_task('/api/import/tasks/'+response.json['task_id'])
            self.assertEqual(task['status'],'failed');post.assert_not_called()
            self.assertIsNone(self.app.article_store.find_url(url))
