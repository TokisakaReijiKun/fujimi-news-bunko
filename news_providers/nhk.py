"""NHK: newsweb article blocks and inline broadcast media."""
import requests
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse
from xml.etree import ElementTree as ET
from . import primitives as p

KEY = 'nhk'
NAME = 'NHKニュース'
DOMAINS = ('news.web.nhk','nhk.or.jp')
ARTICLE_PATH = r'/(?:newsweb/(?:na|articles)/[^/?]+|news/html/\d+/[^/]+\.html)'
OFFICIAL_RSS = 'https://www3.nhk.or.jp/rss/news/cat0.xml'


def html_links(blob, base):
    links = p.public_listing_links(blob, base, DOMAINS, ARTICLE_PATH)
    return [urlunparse(urlparse(url)._replace(scheme='https')) for url in links]


def collect(source, fetch):
    try:
        blob,base=fetch(source['homepage'])
    except (requests.RequestException, TimeoutError) as error:
        response = getattr(error, 'response', None)
        if isinstance(error, requests.HTTPError) and (response is None or response.status_code not in (403, 429, 500, 502, 503, 504)):
            raise
        # NHK's official front page can reject non-browser fetches. Its public
        # RSS feed remains the publisher-owned listing and links to the same
        # NHK article pages used by the reader.
        blob,base=p.fetch_document(fetch,OFFICIAL_RSS,{'Accept':'application/rss+xml,application/xml;q=0.9,*/*;q=0.8'})
        dates = []
        try:
            for node in ET.fromstring(blob).iter():
                if node.tag.split('}')[-1] == 'pubDate' and node.text:
                    stamp = parsedate_to_datetime(node.text)
                    dates.append(stamp.replace(tzinfo=stamp.tzinfo or timezone.utc))
        except (ET.ParseError, ValueError, TypeError):
            pass
        if dates and max(dates) < datetime.now(timezone.utc) - timedelta(days=7):
            raise p.ArticleExtractionError('NHK 官方 RSS 已过期，不能用旧新闻补齐今日日刊。')
    return p.require_links(html_links(blob,base),NAME)


def extract_page(blob, url):
    p.validate_article_url(url,DOMAINS,ARTICLE_PATH)
    soup,records=p.document(blob)
    p.reject_paid_metadata(records)
    heading=p.title(soup,records,excluded=('NHKニュース',))
    scope=p.require_scope(soup,'.content--detail-body, .article-body, [itemprop="articleBody"], main',NAME)
    p.reject_gate(scope,'[data-paywall="true"]')
    p.clean_scope(scope)
    # Recommendation cards are not broadcast story paragraphs or images.
    for node in list(scope.select('[class*="related"], [class*="recommend"], [data-testid*="Related"]')): node.decompose()
    text,origins=p.paragraphs(scope.select('p, h2, h3, h4'),scope)
    pictures=p.images(scope.select('figure img, .article-image img, .content--detail-body img'),scope,origins,url)
    pictures=pictures or p.preview_image(soup,url)
    return p.article_result(KEY,heading,records,text,pictures,p.direct_videos(scope,url))


def fetch_article(url, fetch):
    blob,final=fetch(url)
    result=extract_page(blob,final);result['url']=final
    return result


def postprocess(article, extracted, services):
    # NHK media belongs to the report; save it before waiting for translation.
    result=services.prepare(article,extracted,KEY)
    services.annotate(result)
    services.save(result)
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
