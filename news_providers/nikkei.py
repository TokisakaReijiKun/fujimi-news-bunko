"""Nikkei: reject the main article paywall; never translate a member-only teaser."""
import json
from urllib.parse import urlparse
from . import primitives as p

KEY = 'nikkei'
NAME = '日本経済新聞'
DOMAINS = ('nikkei.com',)
ARTICLE_PATH = r'/article/[A-Z0-9]+/?'
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja-JP,ja;q=0.9',
}


def html_links(blob, base):
    return p.public_listing_links(
        blob, base, DOMAINS, ARTICLE_PATH,
        member_selectors=('[data-paywall="true"]', '[data-testid*="paywall"]', '[class*="premium"]', '[class*="Premium"]', 'img[alt*="会員限定"]'),
        member_terms=('会員限定', '有料会員', '有料記事'))


def collect(source, fetch):
    blob,base=p.fetch_document(fetch,source['homepage'],REQUEST_HEADERS)
    return p.require_links(html_links(blob,base),NAME)


def extract_page(blob, url):
    p.validate_article_url(url,DOMAINS,ARTICLE_PATH)
    soup,records=p.document(blob)
    p.reject_paid_metadata(records)
    gate = soup.select_one('main#main-content, main') or soup
    # This component is also used for the subscription advert below FREE
    # articles. Only the matching article's explicit anonymous-unlocked state
    # distinguishes that advert from a real gate. Conflicting signals reject.
    context = soup.select_one('script#js-k2-hydrate-client-exposed-context')
    try:
        props = json.loads(context.get_text()).get('paywallProps', {}) if context else {}
    except (ValueError, AttributeError):
        props = {}
    lock = props.get('lockStatus', {})
    unlocked = (props.get('kijiId') == urlparse(url).path.rstrip('/').split('/')[-1]
                and lock.get('type') == 'anonymous' and lock.get('isLocked') is False
                and lock.get('isDynamicLocked') is False
                and props.get('isLockedArticle') is False and props.get('isPaidUserOnlyArticle') is False)
    if any(value is True for value in (lock.get('isLocked'), lock.get('isDynamicLocked'),
                                      props.get('isLockedArticle'), props.get('isPaidUserOnlyArticle'))):
        raise p.PaidArticleError('日经本文为会员限定文章。')
    p.reject_gate(gate, '[data-testid="paywall"], [data-paywall="true"]')
    if gate.select_one('[class*="mainPaywall"]') and not unlocked:
        raise p.PaidArticleError('日经本文存在会员阅读门槛。')
    heading=p.title(soup,records)
    scope=p.require_scope(soup,'main#main-content > article, main#main-content article',NAME)
    p.clean_scope(scope)
    text,origins=p.paragraphs(scope.select('p[class*="paragraph_"], h2, h3'),scope)
    pictures=p.images(scope.select('figure:not([data-optimizely-selector]) img'),scope,origins,url) or p.preview_image(soup,url)
    return p.article_result(KEY,heading,records,text,pictures,p.direct_videos(scope,url))


def fetch_article(url, fetch):
    blob,final=p.fetch_document(fetch,url,REQUEST_HEADERS)
    result=extract_page(blob,final);result['url']=final
    return result


def postprocess(article, extracted, services):
    # Paywall validation is completed by this module before preparing the article.
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
