"""Yomiuri: articleBody paragraphs, figures and no share-dialog messages."""
from . import primitives as p

KEY = 'yomiuri'
NAME = '読売新聞'
DOMAINS = ('yomiuri.co.jp',)
ARTICLE_PATH = r'/(?:[^/]+/)+\d{8}-[A-Z0-9]+/?'


def html_links(blob, base):
    return p.public_listing_links(
        blob, base, DOMAINS, ARTICLE_PATH,
        member_selectors=('[data-paywall="true"]', '[data-testid="paywall"]', '[class*="premium"]'),
        member_terms=('会員限定', '有料記事', '読売ID'))


def collect(source, fetch):
    blob,base=fetch(source['homepage'])
    return p.require_links(html_links(blob,base),NAME)


def extract_page(blob, url):
    p.validate_article_url(url,DOMAINS,ARTICLE_PATH)
    soup,records=p.document(blob)
    p.reject_paid_metadata(records)
    p.reject_gate(soup.select_one('article.article-content') or soup,'[data-paywall="true"], [data-testid="paywall"]')
    heading=p.title(soup,records)
    scope=p.require_scope(soup,'article.article-content .p-main-contents',NAME)
    p.clean_scope(scope)
    nodes=scope.select('p[itemprop="articleBody"]') or scope.select('p[class^="par"]')
    text,origins=p.paragraphs(nodes,scope,exclude=('記事をシェアする','完了しました'))
    pictures=p.images(scope.select('figure img'),scope,origins,url) or p.preview_image(soup,url)
    return p.article_result(KEY,heading,records,text,pictures,p.direct_videos(scope,url))


def fetch_article(url, fetch):
    blob,final=fetch(url)
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
