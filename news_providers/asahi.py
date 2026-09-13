"""Asahi: article body only; membership gates before any storage or translation."""
import re
from . import primitives as p

KEY = 'asahi'
NAME = '朝日新聞'
DOMAINS = ('asahi.com',)
ARTICLE_PATH = r'/articles/[A-Z0-9]+\.html'
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja-JP,ja;q=0.9',
}


def html_links(blob, base):
    return p.public_listing_links(
        blob, base, ('www.asahi.com','asahi.com'), ARTICLE_PATH,
        member_selectors=('[data-paywall="true"]', '[data-testid*="paywall"]', '[class*="premium"]', '[class*="Premium"]', '[class*="paywall"]', 'img[alt="有料記事"]'),
        member_terms=('会員限定', '有料記事', '有料会員', 'プレミアム'))


def collect(source, fetch):
    blob,base=p.fetch_document(fetch,source['homepage'],REQUEST_HEADERS)
    return p.require_links(html_links(blob,base),NAME)


def extract_page(blob, url):
    p.validate_article_url(url,DOMAINS,ARTICLE_PATH)
    soup,records=p.document(blob)
    p.reject_paid_metadata(records)
    gate=soup.select_one('main, #MainInner, article') or soup
    if gate.select_one('[data-paywall="true"], [data-testid="paywall"], .premium-block, .paywall'):
        raise p.PaidArticleError('本文为付费或会员限定文章，未收录。')
    heading=p.title(soup,records)
    # Current Asahi pages moved the article text out of the historical
    # ArticleText wrapper. The page main element holds the report paragraphs;
    # source-specific promotion copy is removed below.
    scope=soup.select_one('.article-body, .ArticleText, #MainInner .ArticleBody, [itemprop="articleBody"]')
    fallback_main = scope is None
    if fallback_main:
        if not records:
            raise p.ArticleExtractionError(NAME+'：新版页面缺少文章元数据，已跳过。')
        scope=p.require_scope(soup,'main#main > div.nfyQp',NAME)
    p.reject_gate(scope, '[data-paywall="true"], [data-testid="paywall"]')
    p.clean_scope(scope)
    paragraphs=[]
    subscription_copy=False
    for node in scope.find_all('p'):
        value=node.get_text(' ',strip=True)
        if re.search(r'(?:有料会員になると|この記事の続きが読める|有料記事が読み放題|無料期間中に解約)',value):
            subscription_copy=True
            continue
        paragraphs.append(node)
    if not paragraphs and subscription_copy:
        raise p.PaidArticleError('原站提示本文需会员订阅，未收录。')
    text,origins=p.paragraphs(paragraphs,scope)
    pictures=p.images(scope.select('figure img, .Image img, .article-image img'),scope,origins,url) or p.preview_image(soup,url)
    return p.article_result(KEY,heading,records,text,pictures,p.direct_videos(scope,url))


def fetch_article(url, fetch):
    blob,final=p.fetch_document(fetch,url,REQUEST_HEADERS)
    result=extract_page(blob,final);result['url']=final
    return result


def postprocess(article, extracted, services):
    result=services.prepare(article,extracted,KEY)
    services.annotate(result)
    services.save(result)
    services.translate(result,seconds=90)
    services.save(result)
    return services.media(result,extracted,seconds=60)


def retranslate(article, services):
    article['failure_reason']=''
    services.translate(article,seconds=90,force=True)
    result=services.save(article)
    if result.get('failure_reason'):
        raise ValueError(result['failure_reason'])
    return result
