import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from article_extraction import extract_page, fetch_article, PaidArticleError, ArticleExtractionError
from article_media import cache_media
from server import create_app, ruby


SANK = 'https://www.sankei.com/article/20260907-ABCDEFGHIJ/'
YOMI = 'https://www.yomiuri.co.jp/economy/20260907-GYT1T00275/'
NIKKEI = 'https://www.nikkei.com/article/DGXTEST/'
YAHOO = 'https://news.yahoo.co.jp/articles/' + 'a' * 40


def html(body, head=''):
    return f'<html><head>{head}</head><body>{body}</body></html>'.encode()


def yahoo(body, extra=''):
    return html(f'<article id="uamods"><header><h1>記事の見出し</h1><p>配信時刻</p></header><div class="article_body">{body}</div><section><p>関連記事</p></section>{extra}</article>')


class ArticleExtractionTests(unittest.TestCase):
    def test_furigana_never_changes_original_punctuation(self):
        from bs4 import BeautifulSoup
        for text in ('【バンコク＝田畑清二】インドの乗用車。', '価格は１００円。「本＆新聞」<読む>。'):
            soup = BeautifulSoup(ruby(text), 'html.parser')
            for rt in soup.select('rt'): rt.decompose()
            self.assertEqual(soup.get_text(), text)

    def test_sankei_caption_position_and_no_recommendation_media(self):
        page = html('''<h1>見出し</h1><article class="article-wrapper free"><div class="article-body">
          <figure class="article-image"><a href="/photo/one"><img src="https://www.sankei.com/image.jpg"/></a><figcaption>写真の説明（撮影者）</figcaption></figure>
          <p class="article-text">最初の段落。</p><figure class="article-image"><img src="/second.jpg"/><figcaption>二枚目</figcaption></figure>
          <p class="article-text">次の段落。</p><p>広告の文言</p></div>
          <article class="storycard"><figure><img src="/unrelated.jpg"/></figure><p>推薦</p></article></article>''')
        result = extract_page(page, SANK)
        self.assertEqual(result['paragraphs'], ['最初の段落。', '次の段落。'])
        self.assertEqual(len(result['images']), 2)
        self.assertEqual(result['images'][0]['caption'], '写真の説明（撮影者）')
        self.assertEqual([i['position'] for i in result['images']], [-1, 1])
        self.assertEqual(result['images'][1]['url'], 'https://www.sankei.com/second.jpg')

    def test_yomiuri_body_only_keeps_legitimate_words(self):
        page = html('''<h1>見出し</h1><article class="article-content"><p class="sns-share-popover-explain">記事をシェアする</p><div role="dialog"><p>完了しました</p></div><div class="p-main-contents"><p itemprop="articleBody">工事が完了しました、と発表した。</p><figure class="wp-caption"><img src="/map.jpg"/><figcaption>地図</figcaption></figure><p itemprop="articleBody">第二段落。</p><img src="/media/bnr_gps.png"/><p class="note">会員サービス</p></div></article>''')
        result = extract_page(page, YOMI)
        self.assertEqual(result['paragraphs'], ['工事が完了しました、と発表した。', '第二段落。'])
        self.assertEqual(len(result['images']), 1)

    def test_paid_gates_arrays_graphs_false_strings_and_visible_banner(self):
        schemas = [
            [{'@type':'NewsArticle','isAccessibleForFree':False}],
            {'@graph':[{'@type':'NewsArticle','isAccessibleForFree':'false'}]},
            {'@type':['Article','NewsArticle'],'hasPart':{'isAccessibleForFree':False}},
        ]
        body = '<main id="main-content"><article><h1>見出し</h1><p class="paragraph_x">見える冒頭。</p></article></main>'
        for schema in schemas:
            with self.assertRaises(PaidArticleError):
                extract_page(html(body, '<script type="application/ld+json">'+json.dumps(schema)+'</script>'), NIKKEI)
        for marker in ['<div class="mainPaywall_hash">会員限定</div>', '<p>この記事は会員限定です。登録すると続きをお読みいただけます。</p>']:
            with self.assertRaises(PaidArticleError): extract_page(html(body.replace('</article>', marker+'</article>')), NIKKEI)
        # A generic subscription advertisement is not evidence that the article is gated.
        free = body.replace('</article>', '<aside><p>有料会員募集中</p></aside></article>')
        self.assertEqual(extract_page(html(free), NIKKEI)['paragraphs'], ['見える冒頭。'])

    def test_yahoo_paragraphs_title_byline_and_pagination(self):
        first = yahoo('<p class="provider">通信社</p><p class="yjSlinkDirectlink">第一段落。\n\n第二段落。</p><p>執筆者名</p>', f'<a href="{YAHOO}?page=2">次へ</a>')
        second = yahoo('<p class="yjSlinkDirectlink">第三段落。<br/><br/>第四段落。</p><p>関連記事</p>')
        requests = []
        def fetch(url):
            requests.append(url)
            return (second if 'page=2' in url else first), url
        result = fetch_article(YAHOO+'?page=2', fetch)
        self.assertEqual(requests, [YAHOO, YAHOO+'?page=2'])
        self.assertEqual(result['title'], '記事の見出し')
        self.assertEqual(result['paragraphs'], ['第一段落。','第二段落。','第三段落。','第四段落。'])
        self.assertEqual(result['url'], YAHOO)

    def test_yahoo_rejects_cached_page_and_changed_layout(self):
        with self.assertRaises(ArticleExtractionError):
            fetch_article(YAHOO, lambda _: (html('<h1>Yahoo!ニュース</h1><p>一覧</p>'), 'https://news.yahoo.co.jp/cached-pages/20260907'))
        with self.assertRaises(ArticleExtractionError):
            extract_page(yahoo('<p>通信社と推薦だけ</p>'), YAHOO)
        first = yahoo('<p class="yjSlinkDirectlink">第一段落。</p>', f'<a href="{YAHOO}?page=2">2</a>')
        with self.assertRaises(ArticleExtractionError):
            fetch_article(YAHOO, lambda _: (first, YAHOO))

    def test_yahoo_drops_structural_photo_recommendation_without_title_matching(self):
        body = yahoo('<p class="yjSlinkDirectlink">正文。</p><aside class="related-photo"><p class="yjSlinkDirectlink">【写真】别的推荐标题</p></aside>')
        self.assertEqual(extract_page(body, YAHOO)['paragraphs'], ['正文。'])

    def test_yahoo_drops_related_photo_anchor_by_data_marker(self):
        body = yahoo('<p class="yjSlinkDirectlink">正文。</p>'
                     '<p class="yjSlinkDirectlink"><a href="https://www.yomiuri.co.jp/pluralphoto/20260912-GYT1I00160/?from=yhd" '
                     'data-cl-params="_cl_vmodule:related;_cl_link:photo;_cl_position:1">【表】任意标题</a></p>')
        self.assertEqual(extract_page(body, YAHOO)['paragraphs'], ['正文。'])

    def test_yahoo_keeps_article_subheading(self):
        body = yahoo('<p class="yjSlinkDirectlink">正文。</p>'
                     '<h2 class="sc-zniwbk-1 ezQBRj">単純作業ばかり</h2>'
                     '<p class="yjSlinkDirectlink">続き。</p>')
        self.assertEqual(extract_page(body, YAHOO)['paragraphs'], ['正文。', '単純作業ばかり', '続き。'])

    def test_image_cache_validation_and_serving(self):
        image = io.BytesIO()
        Image.new('RGB', (64, 40), 'green').save(image, 'PNG')
        content = image.getvalue()
        extracted = {'images':[{'url':'https://example.com/a.png','caption':'図注','link':'https://example.com/photo','position':-1}], 'videos':[]}
        with tempfile.TemporaryDirectory() as directory:
            cached = cache_media(extracted, Path(directory)/'media', lambda _: (content, 'https://example.com/a.png'))
            self.assertEqual(cached['image_captions'], ['図注'])
            self.assertEqual((Path(directory)/'media'/cached['image_paths'][0]).read_bytes(), content)
            app = create_app(directory)
            client = app.test_client()
            created = client.post('/api/articles/text',json={'title':'Image test','text':'記事。'}).json
            app.article_store.attach_cached(created['id'],cached,Path(directory)/'media')
            new_path = client.get('/api/articles/'+str(created['id'])).json['image_paths'][0]
            with client.get(new_path) as response:
                self.assertEqual(response.status_code,200)
            with client.get('/api/media/'+cached['image_paths'][0]) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/png')
                self.assertEqual(response.data, content)
            self.assertEqual(client.get('/api/media/../../.env').status_code, 404)
            bad = cache_media(extracted, Path(directory)/'media', lambda _: (b'<html>not image</html>', 'https://example.com/a.png'))
            self.assertEqual(bad['image_paths'], [])
            self.assertTrue(bad['media_warnings'])
            import gc
            gc.collect()

    def test_paid_import_never_inserts_or_translates(self):
        page = html('<main><h1>会員限定記事</h1><p>この記事は会員限定です。</p><p>冒頭</p></main>')
        with tempfile.TemporaryDirectory() as directory:
            client = create_app(directory).test_client()
            with patch('server.public_url'), patch('server.download', return_value=(page, NIKKEI)), patch('server.translate') as translate:
                response = client.post('/api/import/tasks', json={'url':NIKKEI})
                task_id = response.json['task_id']
                import time
                for _ in range(100):
                    task = client.get('/api/import/tasks/'+task_id).json
                    if task['status'] == 'failed': break
                    time.sleep(.01)
                self.assertEqual(task['status'], 'failed')
                translate.assert_not_called()
                self.assertEqual(client.get('/api/days').json, [])
            import gc
            gc.collect()
