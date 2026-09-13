"""Sankei: article-text paragraphs with article-image figure captions."""
from . import primitives as p

KEY = 'sankei'
NAME = '産経新聞'
DOMAINS = ('sankei.com',)
ARTICLE_PATH = r'/article/\d{8}-[A-Z0-9]+/?'


def html_links(blob, base):
    return p.public_listing_links(
        blob, base, DOMAINS, ARTICLE_PATH,
        member_selectors=('[data-paywall="true"]', '[data-testid="paywall"]', '[class*="premium"]'),
        member_terms=('会員限定', '有料記事', '産経電子版'))


def collect(source, fetch):
    blob,base=fetch(source['homepage'])
    return p.require_links(html_links(blob,base),NAME)


def extract_page(blob, url):
    p.validate_article_url(url,DOMAINS,ARTICLE_PATH)
    soup,records=p.document(blob)
    p.reject_paid_metadata(records)
    p.reject_gate(soup.select_one('main') or soup,'article.article-wrapper.premium, [data-paywall="true"]')
    heading=p.title(soup,records,excluded=('産経ニュース',))
    scope=p.require_scope(soup,'article.article-wrapper .article-body',NAME)
    p.clean_scope(scope)
    text,origins=p.paragraphs(scope.select('p.article-text, h2.article-text, h3.article-text, h2, h3'),scope,
                              exclude=('◇', '◇ '))
    pictures=p.images(scope.select('figure.article-image img'),scope,origins,url) or p.preview_image(soup,url)
    return p.article_result(KEY,heading,records,text,pictures,p.direct_videos(scope,url))


def fetch_article(url, fetch):
    blob,final=fetch(url)
    result=extract_page(blob,final);result['url']=final
    return result


def postprocess(article, extracted, services):
    result=services.prepare(article,extracted,KEY)
    services.annotate(result)
    services.save(result)
    # Save the figures with their captions as a unit before translation.
    result=services.media(result,extracted,seconds=60)
    services.translate(result,seconds=90)
    return services.save(result)


def retranslate(article, services):
    article['failure_reason']=''
    services.translate(article,seconds=90,force=True)
    result=services.save(article)
    if result.get('failure_reason'):
        raise ValueError(result['failure_reason'])
    return result
