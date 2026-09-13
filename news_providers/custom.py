"""Fallback exclusively for user-configured sites outside the six publishers."""
from urllib.parse import urljoin, urlparse
from . import primitives as p

KEY='custom'
NAME='自定义来源'
DOMAINS=()
ARTICLE_PATH=r'/(?:articles?|news)/.+'


def html_links(blob, base):
    return p.filter_links(p.listing_links(blob,base),base,(urlparse(base).hostname,),ARTICLE_PATH)


def collect(source, fetch):
    blob,base=fetch(source['homepage'])
    links=p.feed_links(blob,base)
    if links: return links
    links=html_links(blob,base)
    if links: return links
    soup,_=p.document(blob)
    alternate=soup.select_one('link[type="application/rss+xml"],link[type="application/atom+xml"],link[type="application/rdf+xml"]')
    if alternate and alternate.get('href'):
        blob,base=fetch(urljoin(base,alternate['href']))
        return p.require_links(p.feed_links(blob,base),NAME)
    return p.require_links([],NAME)


def extract_page(blob, url):
    soup,records=p.document(blob)
    p.reject_paid_metadata(records)
    p.reject_gate(soup.select_one('main,article') or soup,'[data-paywall="true"], [data-testid="paywall"]')
    heading=p.title(soup,records)
    scope=soup.select_one('[itemprop="articleBody"],article,main') or soup.body or soup
    p.clean_scope(scope)
    text,origins=p.paragraphs(scope.find_all('p'),scope)
    pictures=p.images(scope.select('figure img'),scope,origins,url) or p.preview_image(soup,url)
    return p.article_result(KEY,heading,records,text,pictures,p.direct_videos(scope,url))


def fetch_article(url, fetch):
    blob,final=fetch(url)
    if urlparse(final).hostname!=urlparse(url).hostname:
        raise p.ArticleExtractionError('自定义来源重定向到其他网站，已停止采集。')
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
