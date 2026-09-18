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
    def test_asahi_body_headings_keep_text_without_links_and_image_positions(self):
        blob=('<meta charset="utf-8"><main><h1>記事</h1><div class="ArticleText">'
              '<p>導入。</p><h2 class="smgSC">連載「<a href="//www.asahi.com/topics/word/test.html">供述調書</a>のわな」</h2>'
              '<figure><img src="https://example.com/photo.jpg"><figcaption>図</figcaption></figure>'
              '<p>本文。</p><h3>補足</h3><aside><h2>おすすめ</h2></aside></div><h2>連載一覧</h2></main>').encode()
        result=asahi.extract_page(blob,URLS['asahi'])
        self.assertEqual(result['paragraphs'],['導入。','連載「供述調書のわな」','本文。','補足'])
        self.assertEqual(result['paragraph_kinds'],['paragraph','heading-2','paragraph','heading-3'])
        self.assertEqual(result['images'][0]['position'],2)
        self.assertEqual(result['paragraph_links'],[])
    def test_yomiuri_keeps_headings_in_body_order_and_image_positions(self):
        for attr in ('itemprop="articleBody"','class="par1"'):
            blob=('<meta charset="utf-8"><h1>記事</h1><article class="article-content"><div class="p-main-contents">'
                  '<h2>幸せな瞬間、確かにあった</h2><p '+attr+'>本文。</p>'
                  '<figure><img src="https://example.com/photo.jpg"><figcaption>写真</figcaption></figure>'
                  '<h2>次の見出し</h2><p '+attr+'>次の本文。</p>'
                  '<aside><h2>あわせて読みたい</h2><p '+attr+'>推薦</p></aside>'
                  '<p>記事をシェアする</p></div></article>').encode()
            result=yomiuri.extract_page(blob,URLS['yomiuri'])
            self.assertEqual(result['paragraphs'],['幸せな瞬間、確かにあった','本文。','次の見出し','次の本文。'])
            self.assertEqual(result['paragraph_kinds'],['heading-2','paragraph','heading-2','paragraph'])
            self.assertEqual(result['images'][0]['position'],2)

    def test_nikkei_report_box_keeps_breaks_bold_label_and_safe_links(self):
        from news_providers.services import ArticleServices
        from bs4 import BeautifulSoup
        import html
        url='https://partsa.nikkei.com/report.pdf?part=1&download=1'
        blob=page('nikkei').replace(b'</article>',
            ('<div class="container_c1tzahnc"><strong>調査報告書</strong><br>前半: '
             '<a href="'+html.escape(url)+'">PDF</a><br>後半: <a href="javascript:alert(1)">危険</a></div></article>').encode(),1)
        result=nikkei.extract_page(blob,URLS['nikkei'])
        article={k:result[k] for k in ('paragraphs','paragraph_kinds','paragraph_formats','paragraph_links')}
        service=ArticleServices(None,translate=None,ruby=html.escape,now=None,stage=None,
            reset_budget=None,check=lambda:None,download=None,translation_enabled=None,cancelled_error=Exception)
        service.annotate(article)
        soup=BeautifulSoup(article['furigana_paragraphs'][-1],'html.parser')
        self.assertEqual(result['paragraph_kinds'][-1],'box-plain')
        self.assertEqual(len(soup.select('br')),2)
        self.assertEqual(soup.strong.get_text(),'調査報告書')
        self.assertEqual([a['href'] for a in soup.select('a')],[url])
        self.assertNotIn('article-box-heading',str(soup))
        self.assertEqual(soup.get_text('\n'), '調査報告書\n前半: \nPDF\n後半: 危険')

    def test_nikkei_drops_company_entity_links_but_keeps_content_links(self):
        report='https://partsa.nikkei.com/report.pdf'
        blob=page('nikkei').replace(
            '第一段。'.encode(),
            ('<a href="/nkd/company/?scode=9502">中部電力</a>は報告書を公表した。'
             '<a href="'+report+'">報告書本文</a>').encode(),1)
        result=nikkei.extract_page(blob,URLS['nikkei'])
        self.assertEqual(result['paragraphs'][0],'中部電力は報告書を公表した。報告書本文')
        self.assertEqual(result['paragraph_links'][0],[{
            'start':14,'end':19,'url':report,
        }])

    def test_yahoo_lead_survives_embedded_related_photo_link(self):
        blob=page('yahoo').replace('第一段。\n\n第二段。'.encode(),
            '第一段。\n\n<a href="https://example.com/photo" data-cl-params="_cl_vmodule:related;_cl_link:photo">推薦</a>\n\n第二段。'.encode())
        result=yahoo.extract_page(blob,URLS['yahoo'])
        self.assertEqual(result['paragraphs'],['第一段。','第二段。'])

    def test_nikkei_plain_box_is_not_a_heading(self):
        blob=page('nikkei').replace(b'</article>',
            '<div class="container_c1tzahnc">こじゃ・げんた　06年東大薬卒。42歳。</div></article>'.encode(),1)
        result=nikkei.extract_page(blob,URLS['nikkei'])
        self.assertEqual(result['paragraph_kinds'][-1],'box-plain')
        self.assertEqual(result['paragraph_formats'][-1],[])
        from news_providers.services import ArticleServices
        service=ArticleServices(None,translate=None,ruby=lambda t:t,now=None,stage=None,
            reset_budget=None,check=lambda:None,download=None,translation_enabled=None,cancelled_error=Exception)
        article={k:result[k] for k in ('paragraphs','paragraph_kinds','paragraph_formats')}
        service.annotate(article)
        self.assertEqual(article['furigana_paragraphs'][-1],result['paragraphs'][-1])

    def test_nhk_marked_headings_inline_images_and_related_cards(self):
        url=URLS['nhk']
        marked=('導入。\n\n## 古謝氏「沖縄を前に進めていきたい」\n\n'
                '![写真の説明](https://img.web.nhk/news/story/photo.jpg)\n\n本文。\n\n'
                ':::nw--colored {style=background-color:red}\n## 各党反応\n:::\n\n----\n\n'
                ':::nw--link-type4 {href=https://news.web.nhk/newsweb/na/other}\n'
                '![関連記事](https://img.web.nhk/news/other.jpg)\n\n**関連記事**\n:::\n')
        data={'type':'NewsArticle','id':url.rsplit('/',1)[-1],'canonical':url,'headline':'見出し',
              'articleBody':'導入。\n\n古謝氏「沖縄を前に進めていきたい」\n\n写真の説明\n\n本文。\n\n各党反応\n\n関連記事\n\n関連記事',
              'detailedArticleBody':{'markedLead':'','markedBody':marked},
              'image':{'medium':{'url':'https://imgu.web.nhk/cover.jpg'}},
              'citation':[{'image':'https://img.web.nhk/unrelated.jpg'}]}
        result=nhk._api_article(data,url)
        self.assertEqual(result['paragraphs'],['導入。','古謝氏「沖縄を前に進めていきたい」','本文。','各党反応'])
        self.assertEqual(result['paragraph_kinds'],['paragraph','heading-2','paragraph','heading-2'])
        self.assertEqual([(i['position'],i['caption']) for i in result['images']],[(-1,''),(2,'写真の説明')])
        self.assertEqual(len(result['images']),2)
        with self.assertRaises(ArticleExtractionError):nhk._api_article(dict(data,articleBody='Other story'),url)
        for source in ('https://img.web.nhk.evil.example/a.jpg','http://img.web.nhk/a.jpg'):
            bad=dict(data,detailedArticleBody={'markedBody':marked.replace('https://img.web.nhk/news/story/photo.jpg',source)})
            with self.assertRaises(ArticleExtractionError):nhk._api_article(bad,url)

    def test_asahi_gold_key_and_unlabelled_breaking_rail_are_filtered_before_fetch(self):
        paid=URLS['asahi'];free=paid.replace('TEST','FREE');breaking=paid.replace('TEST','BREAKING')
        for badge in ('<figure class="c-icon c-icon--keyGold"><img src="//www.asahicom.jp/images/icon/top/icon__keyGold.svg" alt="有料記事"></figure>',
                      '<img alt="" src="//www.asahicom.jp/images/icon/top/icon__keyGold.svg">'):
            blob=(f'<a href="{paid}">duplicate</a><div class="c-articleModule"><h2><a href="{paid}?ref=1">Paid</a></h2>{badge}</div>'
                  f'<div class="c-articleModule"><h2><a href="{free}">Free</a></h2></div>'
                  f'<ul class="p-breaking__List"><li class="p-breaking__listItem"><a href="{breaking}">No membership label</a></li></ul>').encode()
            fetch=Mock(return_value=(blob,'https://www.asahi.com/'))
            with patch.object(asahi,'fetch_article',side_effect=AssertionError('must not fetch a paid body')):
                self.assertEqual(asahi.collect({'homepage':'https://www.asahi.com/'},fetch),[free])
            fetch.assert_called_once()

    def test_asahi_title_area_paid_text_link_or_badge_blocks_teaser(self):
        for marker in ('<a href="//www.asahi.com/news/gold.html?iref=com_gold">有料記事</a>',
                       '<figure class="c-icon c-icon--keyGold"><img alt="有料記事"></figure>'):
            blob=('<meta charset="utf-8"><main><div class="y_Qv3"><h1>見出し</h1><div class="mhPng">'+marker+
                  '</div></div><div class="ArticleText"><p>Teaser is still visible.</p></div></main>').encode()
            with self.assertRaises(PaidArticleError):asahi.extract_page(blob,URLS['asahi'])
        free=page('asahi').replace(b'</main>',b'<aside><figure class="c-icon--keyGold"><img alt="paid"></figure></aside></main>')
        self.assertEqual(asahi.extract_page(free,URLS['asahi'])['paragraphs'],['第一段。','第二段。'])

    def test_sankei_heading_kinds_follow_filtered_body_order(self):
        blob=('<meta charset="utf-8"><h1>記事</h1><article class="article-wrapper free"><div class="article-body">'
              '<p class="article-text">最初の段落。</p><p class="article-text">◇</p>'
              '<h2 class="article-middle-headline headline_size-1 block font-bold">かつての「小沢ストリート」は…</h2>'
              '<p class="article-text">本文。</p><h3>補足</h3>'
              '<h2><a href="/other">推薦</a></h2>'
              '<h2 class="article-middle-headline">「いずれは官邸の主に」</h2>'
              '</div></article>').encode()
        result=sankei.extract_page(blob,URLS['sankei'])
        self.assertEqual(result['paragraphs'],['最初の段落。','かつての「小沢ストリート」は…','本文。','補足','「いずれは官邸の主に」'])
        self.assertEqual(result['paragraph_kinds'],['paragraph','heading-2','paragraph','heading-3','heading-2'])

    def test_sankei_paid_lock_is_excluded_before_fetching_article(self):
        paid=URLS['sankei'];free=paid.replace('TEST','FREE')
        for badge in ('<img width="16" height="16" alt="有料会員記事" src="/pf/resources/icons/img_lock-gold.svg?d=1191">',
                      '<img alt="" src="/pf/resources/icons/img_lock-gold.svg?d=1192">'):
            listing=(f'<a href="{paid}">重複</a><li><h3><a href="{paid}?ref=top">有料見出し</a>{badge}</h3></li>'
                     f'<li><h3><a href="{free}">公開本文</a></h3></li>').encode()
            fetch=Mock(return_value=(listing,'https://www.sankei.com/'))
            with patch.object(sankei,'fetch_article',side_effect=AssertionError('paid candidate fetched')):
                self.assertEqual(sankei.collect({'homepage':'https://www.sankei.com/'},fetch),[free])
            fetch.assert_called_once_with('https://www.sankei.com/')

    def test_sankei_main_paid_badge_and_class_reject_but_ranking_badge_does_not(self):
        badge='<img alt="有料会員記事" src="/pf/resources/icons/img_lock-gold.svg?d=1191">'
        for blob in (page('sankei').replace(b'article-wrapper free',b'article-wrapper paid_members'),
                     page('sankei').replace(b'<div class="article-body">',('<div class="article-header"><span class="restrictions">'+badge+'</span></div><div class="article-body">').encode())):
            with self.assertRaises(PaidArticleError):sankei.extract_page(blob,URLS['sankei'])
        free=page('sankei').replace(b'</body>',('<section class="ranking"><h3>'+badge+'</h3></section></body>').encode())
        self.assertEqual(sankei.extract_page(free,URLS['sankei'])['paragraphs'],['第一段。','第二段。'])

    def test_asahi_uses_main_heading_and_srcset_photo_caption(self):
        blob='''<meta charset="utf-8"><title>見出し [県]：朝日新聞</title><h1></h1>
        <script type="application/ld+json">{"@type":"NewsArticle","headline":"見出し [県]：朝日新聞"}</script>
        <main id="main"><h1>見出し</h1><div class="nfyQp"><a href="/photo"><figure>
        <img srcset="//www.asahicom.jp/photo.jpg"><figcaption>本部=撮影日、撮影者<svg></svg></figcaption></figure></a>
        <p>本文。</p></div><figure><img src="/unrelated.jpg"></figure></main>'''.encode()
        result=asahi.extract_page(blob,URLS['asahi'])
        self.assertEqual(result['title'],'見出し')
        self.assertEqual([(i['url'],i['caption']) for i in result['images']], [('https://www.asahicom.jp/photo.jpg','本部=撮影日、撮影者')])

    def test_nhk_never_treats_preview_and_recommendations_as_full_body(self):
        blob=b'<main><h1>Headline</h1><p>Preview...</p><h2>Related</h2><p>Wrong story</p></main>'
        with self.assertRaises(ArticleExtractionError):nhk.extract_page(blob,URLS['nhk'])

    def test_nhk_current_api_checks_identity_and_requires_complete_body(self):
        url=URLS['nhk'];aid=url.rsplit('/',1)[-1]
        data={'type':'NewsArticle','id':aid,'canonical':url,'headline':'見出し',
              'articleBody':'導入。\n\n本文。\n\n小見出し\n\n結び。',
              'detailedArticleBody':{'markedLead':'導入。','markedBody':'本文。\n\n## 小見出し\n\n結び。'},
              'citation':[{'name':'無関係の推薦'}],
              'video':[{'detailedContent':[{'contentUrl':'https://media.vd.st.nhk/news/test/index.m3u8'}]}]}
        result=nhk._api_article(data,url)
        self.assertEqual(result['paragraphs'],['導入。','本文。','小見出し','結び。'])
        self.assertEqual(result['paragraph_kinds'],['paragraph','paragraph','heading-2','paragraph'])
        self.assertEqual(len(result['videos']),1)
        for changed in ({'id':'another'},{'canonical':URLS['asahi']},{'articleBody':''}):
            with self.assertRaises(ArticleExtractionError):nhk._api_article(dict(data,**changed),url)

    def test_nhk_overseas_reader_fetches_full_article_with_one_temporary_session(self):
        url=URLS['nhk'];aid=url.rsplit('/',1)[-1];calls=[];sessions=[]
        def fetch(target,**kwargs):
            calls.append(target)
            if target==url:return b'<main><script id="json-ld-2"></script><p>Preview only</p></main>',url
            sessions.append(kwargs['session'])
            if 'geoip' in target:return b'{"country_name":"Singapore"}',target
            if '/tix/' in target:return b'',url
            data={'type':'NewsArticle','id':aid,'canonical':url,'headline':'本文'}
            if len(calls)>3:data['articleBody']='完全な本文。'
            return json.dumps(data).encode(),target
        result=nhk.fetch_article(url,fetch)
        self.assertEqual(result['paragraphs'],['完全な本文。'])
        self.assertEqual(len({id(s) for s in sessions}),1)
        self.assertEqual(len(calls),5)

    def test_nhk_short_lived_media_authorization_is_not_stored(self):
        stream='https://media.vd.st.nhk/news/story/index.m3u8'
        source={'url':URLS['nhk'],'videos':[stream]}
        services=Mock();services.cancelled_error=WorkCancelled
        services.download.return_value=(b'{"token":"exp=123~acl=/*~hmac=test"}','https://mediatoken.web.nhk/v1/token')
        def authorize(url,fetch,session):session.cookies.set('z_at','test-session',domain='.web.nhk')
        with patch.object(nhk,'_authorize_overseas',side_effect=authorize):
            resolved=nhk._resolve_videos(source,services)
        self.assertIn('hdnts=',resolved['videos'][0])
        self.assertEqual(source['videos'],[stream])
        self.assertNotIn('test-session',str(resolved))

    def test_nikkei_article_heading_box_and_inline_emphasis(self):
        blob = '''<html><meta charset="utf-8"><h1>Podcast</h1>
        <main id="main-content"><article><h1>鈴木健吾、夢の五輪に挑む</h1>
        <section data-track-article-content><p class="paragraph_test">公開本文。</p>
        <div><div><h2>目次</h2></div><br>03:08　日本記録<br>07:24　箱根駅伝<br>13:28　全く頭になかった日本記録<br>17:41　ケガ<br>22:14　船出</div>
        <p class="paragraph_test"><strong onclick="bad()">ゲスト:鈴木健吾さん</strong>（すずき・けんご）</p>
        <p class="paragraph_test"><b>聞き手:浅利そのみさん</b>　紹介。</p>
        <h2>割引適用ならドコモのProは10万円弱も</h2>
        <p class="paragraph_test">公開本文の続き。</p>
        </section><section><h2>関連記事</h2></section></article></main></html>'''.encode()
        result=nikkei.extract_page(blob,URLS['nikkei'])
        self.assertEqual(result['title'],'鈴木健吾、夢の五輪に挑む')
        self.assertEqual(result['paragraph_kinds'],['paragraph','box','paragraph','paragraph','heading-2','paragraph'])
        self.assertEqual(result['paragraphs'][1].splitlines(),['目次','03:08　日本記録','07:24　箱根駅伝','13:28　全く頭になかった日本記録','17:41　ケガ','22:14　船出'])
        self.assertEqual(result['paragraph_formats'][2],[[0,10]])
        self.assertNotIn('関連記事',result['paragraphs'])

    def test_nikkei_player_is_online_embed_not_video_file(self):
        player='https://players.brightcove.net/4504957054001/4oGezvdToL_default/index.html?videoId=6404800298112'
        blob=page('nikkei').replace(b'</article>',f'<iframe src="{player}"></iframe><iframe src="https://players.brightcove.net.evil.example/player/index.html?videoId=123"></iframe><video src="https://example.com/movie.mp4"></video></article>'.encode(),1)
        result=nikkei.extract_page(blob,URLS['nikkei'])
        self.assertEqual(result['video_embeds'],[player])
        self.assertEqual(result['videos'],['https://example.com/movie.mp4'])
        paid=blob.replace(b'</article>',b'<div data-paywall="true"></div></article>',1)
        with self.assertRaises(PaidArticleError):nikkei.extract_page(paid,URLS['nikkei'])

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

    def test_nhk_inline_images_use_temporary_session_and_keep_positions(self):
        url=URLS['nhk'];image_url='https://img.web.nhk/news/photo.jpg'
        data={'type':'NewsArticle','id':url.rsplit('/',1)[-1],'canonical':url,'headline':'見出し',
              'articleBody':'導入。\n\n小見出し\n\n本文。',
              'detailedArticleBody':{'markedLead':'導入。','markedBody':'## 小見出し\n\n![]('+image_url+')\n\n本文。'}}
        def download(target,**kwargs):
            if target==url:return b'<script id="json-ld-2"></script>',url
            if target==image_url:
                self.assertIn('session',kwargs)
                return self.image,target
            return json.dumps(data).encode(),target
        with patch('server.download',side_effect=download),patch('server.public_url'),patch.object(nhk,'_authorize_overseas') as authorize,patch.dict('os.environ',{},clear=True):
            response=self.client.post('/api/import/tasks',json={'url':url})
            task=self.wait_task('/api/import/tasks/'+response.json['task_id'])
            self.assertEqual(task['status'],'completed',task)
            a=task['article'];self.assertEqual(a['paragraph_kinds'],['paragraph','heading-2','paragraph'])
            self.assertEqual(a['image_positions'],[2]);self.assertEqual(a['media_warnings'],[])
            with self.client.get(a['image_paths'][0]) as image_response:self.assertEqual(image_response.data,self.image)
            authorize.assert_called_once()

    def test_sankei_headings_survive_import_storage_and_retranslation(self):
        blob=page('sankei').replace(b'<p class=article-text>',b'<h2 class="article-middle-headline">Section heading</h2><p class=article-text>',1)
        with patch('server.download',side_effect=lambda url,**kwargs:(self.image if url==IMAGE else blob,url)),patch('server.public_url'),patch.dict('os.environ',{'DEEPSEEK_API_KEY':'test-only'},clear=True),patch('server.translate',side_effect=lambda text:['译：'+p for p in text]):
            response=self.client.post('/api/import/tasks',json={'url':URLS['sankei']})
            task=self.wait_task('/api/import/tasks/'+response.json['task_id'])
            self.assertEqual(task['status'],'completed',task)
            article=task['article'];aid=article['id']
            self.assertEqual(article['paragraph_kinds'],['heading-2','paragraph','paragraph'])
            self.assertEqual(self.app.article_store.load(aid)['paragraph_kinds'],article['paragraph_kinds'])
            self.client.post(f'/api/articles/{aid}/retranslate')
            self.assertEqual(self.wait_task(f'/api/articles/{aid}/translation-task')['status'],'completed')
            self.assertEqual(self.client.get(f'/api/articles/{aid}').json['paragraph_kinds'],article['paragraph_kinds'])

    def test_nikkei_formatting_and_downloaded_video_survive_store_and_retranslation(self):
        player='https://players.brightcove.net/4504957054001/4oGezvdToL_default/index.html?videoId=123'
        blob=page('nikkei').replace(b'</article>',f'<div class="container_c1tzahnc"><div><h2>目次</h2></div><br>03:08　第一項<br>07:24　第二項</div><h2>小見出し</h2><p class="paragraph_a"><strong>強調</strong>と&lt;script&gt;。</p><iframe src="{player}"></iframe></article>'.encode(),1)
        def fetch(url,**kwargs):
            if url==URLS['nikkei']:return blob,url
            if url==player:return b'policyKey:"public-test-policy"',url
            if 'edge.api.brightcove.com' in url:
                return json.dumps({'id':'123','name':'番組タイトル','poster':'https://example.com/poster.jpg','sources':[{'src':'https://example.com/test.mp4','container':'MP4','size':16}]}).encode(),url
            if url.endswith('/test.mp4'):return b'\x00\x00\x00\x18ftypisomTEST',url
            return self.image,url
        with patch('server.download',side_effect=fetch),patch('server.public_url'),patch.dict('os.environ',{'DEEPSEEK_API_KEY':'test-only'},clear=True),patch('server.translate',side_effect=lambda text:['译：'+p for p in text]):
            response=self.client.post('/api/import/tasks',json={'url':URLS['nikkei']})
            task=self.wait_task('/api/import/tasks/'+response.json['task_id'])
            self.assertEqual(task['status'],'completed',task)
            a=task['article']
            self.assertEqual(len(a['video_urls']),1)
            self.assertTrue(a['video_urls'][0].startswith('/api/articles/'))
            with self.client.get(a['video_urls'][0]) as response:self.assertEqual(response.data[4:8],b'ftyp')
            self.assertEqual(a['paragraph_kinds'][-2: ],['heading-2','paragraph'])
            from bs4 import BeautifulSoup
            box=BeautifulSoup(a['furigana_paragraphs'][-3],'html.parser')
            for rt in box.select('rt'):rt.decompose()
            self.assertEqual(box.select_one('.article-box-heading').get_text(),'目次')
            self.assertEqual([n.get_text() for n in box.select('.article-box-line')],['03:08　第一項','07:24　第二項'])
            self.assertIn('<strong>',a['furigana_paragraphs'][-1])
            self.assertIn('&lt;script&gt;',a['furigana_paragraphs'][-1])
            self.assertNotIn('<script>',a['furigana_paragraphs'][-1])
            saved=self.app.article_store.load(a['id'])
            self.assertEqual(saved['paragraph_formats'],a['paragraph_formats'])
            self.assertEqual(a['media_warnings'],[])
            self.assertEqual(a['media_title'],'番組タイトル')
            self.client.post(f'/api/articles/{a["id"]}/retranslate')
            again=self.wait_task(f'/api/articles/{a["id"]}/translation-task')
            self.assertEqual(again['status'],'completed')
            self.assertEqual(self.app.article_store.load(a['id'])['furigana_paragraphs'],a['furigana_paragraphs'])

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

    def test_asahi_paid_title_marker_never_reaches_storage_or_postprocessing(self):
        blob=b'<main><div><h1>Paid</h1><a href="/news/gold.html">Member</a></div><div class="ArticleText"><p>Teaser</p></div></main>'
        before=self.app.article_store.ids()
        with patch('server.public_url'),patch.object(asahi,'postprocess') as post,patch('server.download',return_value=(blob,URLS['asahi'])):
            response=self.client.post('/api/import/tasks',json={'url':URLS['asahi']})
            task=self.wait_task('/api/import/tasks/'+response.json['task_id'])
            self.assertEqual(task['status'],'failed')
            post.assert_not_called()
            self.assertEqual(self.app.article_store.ids(),before)

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
