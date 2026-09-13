"""Small HTML/feed operations. No publisher selection or processing pipeline."""
import json
import re
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup


class PaidArticleError(ValueError):
    pass


class ArticleExtractionError(ValueError):
    pass


def schema_nodes(value):
    if isinstance(value, list):
        for child in value: yield from schema_nodes(child)
    elif isinstance(value, dict):
        yield value
        if '@graph' in value: yield from schema_nodes(value['@graph'])


def metadata(soup):
    records = []
    for script in soup.select('script[type="application/ld+json"]'):
        try: value = json.loads(script.get_text())
        except (ValueError, TypeError): continue
        for node in schema_nodes(value):
            types = node.get('@type', [])
            if isinstance(types, str): types = [types]
            if any(t in ('Article', 'NewsArticle', 'ReportageNewsArticle') for t in types): records.append(node)
    return records


def plain(value):
    return str(value.get('@value', '')) if isinstance(value, dict) else str(value or '')


def reject_paid_metadata(records):
    for record in records:
        if str(record.get('isAccessibleForFree')).lower() == 'false':
            raise PaidArticleError('本文为付费或会员限定文章，未收录。')
        parts = record.get('hasPart', [])
        if isinstance(parts, dict): parts = [parts]
        if any(str(p.get('isAccessibleForFree')).lower() == 'false' for p in parts if isinstance(p, dict)):
            raise PaidArticleError('本文包含会员限定内容，未收录。')


def reject_gate(scope, selectors):
    if selectors and scope.select_one(selectors):
        raise PaidArticleError('本文为付费或会员限定文章，未收录。')
    for node in scope.select('p, span, h2, h3, [role="alert"]'):
        text = node.get_text('', strip=True)
        if len(text) < 250 and re.search(r'(?:この記事|この(?:続き|記事)|ここから先).{0,25}(?:会員限定|有料会員|有料記事)|(?:続き|全文)を(?:お)?読(?:みいただく|む)には.{0,20}(?:登録|会員)', text):
            raise PaidArticleError('原站提示本文需会员订阅，未收录。')


def document(blob):
    soup = BeautifulSoup(blob, 'html.parser')
    return soup, metadata(soup)


def require_scope(soup, selectors, publisher):
    scope = soup.select_one(selectors)
    if scope is None: raise ArticleExtractionError(f'{publisher}：未识别正文容器，已跳过。')
    return scope


def clean_scope(scope):
    for node in list(scope.select('script,style,nav,footer,aside,form,noscript,[role="dialog"]')): node.decompose()


def is_noise(node, scope):
    for parent in [node, *node.parents]:
        if parent is scope: break
        if getattr(parent, 'name', '') in ('header', 'footer', 'nav', 'aside', 'form', 'button', 'figcaption'): return True
        attrs = ' '.join(parent.get('class', [])) + ' ' + str(parent.get('id', ''))
        if re.search(r'(?:^|[\s_-])(?:related|recommend|sns|share|advert|ranking|paywall|author|copyright)(?:[\s_-]|$)', attrs, re.I): return True
        if parent.get('role') in ('dialog', 'alert') or parent.get('aria-hidden') == 'true': return True
    return False


def paragraphs(nodes, scope, *, split_blank_lines=False, exclude=()):
    values, origins = [], []
    for node in nodes:
        if is_noise(node, scope) or node.find_parent('a'): continue
        for annotation in node.select('rt,rp'): annotation.decompose()
        for br in node.find_all('br'): br.replace_with('\n')
        text = node.get_text('', strip=False).replace('\r', '').strip()
        linked = ''.join(a.get_text('', strip=True) for a in node.find_all('a'))
        if not text or linked == text or text in exclude: continue
        for piece in re.split(r'\n\s*\n', text) if split_blank_lines else [text]:
            piece = re.sub(r'\s*\n\s*', ' ', piece).strip()
            if piece: values.append(piece); origins.append(node)
    if not values: raise ArticleExtractionError('未找到可公开阅读的正文，已跳过。')
    if sum(map(len, values)) > 150000: raise ArticleExtractionError('文章过长，已停止导入。')
    return values, origins


def title(soup, records, *, selector='h1', excluded=()):
    heading = soup.select_one(selector)
    value = heading.get_text(' ', strip=True) if heading else plain(records[0].get('headline')) if records else ''
    value = value or (soup.title.get_text(' ', strip=True) if soup.title else '')
    if not value or value in excluded: raise ArticleExtractionError('未识别到文章标题，已跳过。')
    return value


def images(nodes, scope, origins, url, caption_for=None):
    order = {id(n): i for i, n in enumerate(scope.descendants)}
    result, seen = [], set()
    for img in nodes:
        if is_noise(img, scope): continue
        raw = img.get('data-src') or img.get('data-original') or img.get('src', '')
        if not raw or raw.startswith('data:'): continue
        src = urljoin(url, raw)
        if urlparse(src).scheme not in ('http', 'https') or src in seen: continue
        if re.search(r'(?:logo|banner|bnr_|icon|spacer)', urlparse(src).path, re.I): continue
        figure = img.find_parent('figure')
        caption = caption_for(img) if caption_for else figure.select_one('figcaption') if figure else None
        text = caption.get_text(' ', strip=True) if caption else img.get('alt', '')
        anchor = img.find_parent('a')
        link = urljoin(url, anchor.get('href', '')) if anchor else src
        if urlparse(link).scheme not in ('http', 'https'): link = src
        before = sum(order.get(id(p), 0) < order.get(id(img), 0) for p in origins)
        result.append(dict(url=src,caption=text,link=link,position=-1 if before==0 else before));seen.add(src)
    return result


def preview_image(soup, url):
    og = soup.select_one('meta[property="og:image"]')
    if not og: return []
    src = urljoin(url, og.get('content', ''))
    return [dict(url=src,caption='',link=src,position=-1)] if urlparse(src).scheme in ('http','https') else []


def direct_videos(scope, url):
    result = []
    for node in scope.select('video[src],video source[src], [data-video-url], [data-video-src], [data-movie-url]'):
        raw = node.get('src') or node.get('data-video-url') or node.get('data-video-src') or node.get('data-movie-url')
        src = urljoin(url, raw or '')
        if urlparse(src).scheme in ('http','https') and re.search(r'\.(mp4|webm)$',urlparse(src).path,re.I) and src not in result: result.append(src)
    for node in scope.select('iframe[src]'):
        src = urljoin(url, node.get('src',''))
        if urlparse(src).scheme in ('http','https') and any(token in src.lower() for token in ('video','movie','player')) and src not in result:
            result.append(src)
    return result


def article_result(key, heading, records, text, pictures, videos, *, warnings=None):
    record = records[0] if records else {}
    author = record.get('author', {})
    if isinstance(author,list): author=author[0] if author else {}
    return dict(source_key=key,title=heading,published_at=plain(record.get('datePublished')) or None,
                paragraphs=text,images=pictures,videos=videos,next_url=None,
                publisher_name=plain(author.get('name')) if isinstance(author,dict) else '',media_warnings=warnings or [])


def host_matches(url, domains):
    host = (urlparse(url).hostname or '').lower()
    return any(host == d or host.endswith('.'+d) for d in domains)


def validate_article_url(url, domains, pattern):
    p = urlparse(url)
    if p.scheme not in ('http','https') or not host_matches(url,domains) or not re.fullmatch(pattern,p.path):
        raise ArticleExtractionError('地址不是该来源的新闻正文页，已跳过。')


def feed_links(blob, base):
    try: xml=ET.fromstring(blob)
    except ET.ParseError: return []
    if xml.tag.split('}')[-1].lower() not in ('rss','rdf','feed'): return []
    result=[]
    for entry in xml.iter():
        if entry.tag.split('}')[-1] not in ('item','entry'): continue
        for node in entry:
            if node.tag.split('}')[-1]=='link' and node.get('rel','alternate')=='alternate':
                link=urljoin(base,node.get('href') or (node.text or '').strip())
                if urlparse(link).scheme in ('http','https'): result.append(link)
                break
    return list(dict.fromkeys(result))


def filter_links(links, base, domains, pattern):
    result=[]
    for link in links:
        url=urljoin(base,link);p=urlparse(url)
        if p.scheme not in ('http','https') or not host_matches(url,domains) or not re.fullmatch(pattern,p.path): continue
        canonical=urlunparse(p._replace(query='',fragment=''))
        if canonical not in result: result.append(canonical)
    return result


def listing_links(blob, base):
    return feed_links(blob,base) or [a['href'] for a in BeautifulSoup(blob,'html.parser').select('a[href]')]


def public_listing_links(blob, base, domains, pattern, *, member_selectors=(), member_terms=()):
    """Return article links from listing cards that are visibly public.

    The publisher passes its own membership badges and wording.  This helper
    only applies those supplied rules to a single listing document; it never
    decides a publisher or tries to parse an article body.
    """
    if feed_links(blob, base):
        return filter_links(feed_links(blob, base), base, domains, pattern)
    soup = BeautifulSoup(blob, 'html.parser')
    blocked = set()
    for selector in member_selectors:
        blocked.update(id(node) for node in soup.select(selector))
    terms = re.compile('|'.join(f'(?:{term})' for term in member_terms), re.I) if member_terms else None
    links = []
    denied_urls = set()
    for anchor in soup.select('a[href]'):
        parents = [anchor, *anchor.parents]
        if any(id(node) in blocked for node in parents):
            denied_urls.update(filter_links([anchor['href']], base, domains, pattern))
            continue
        # Publishers use different card elements. Prefer a semantic card, then
        # a component-like container, without reaching page-wide navigation.
        card = next((node for node in parents if getattr(node, 'name', '') in ('article', 'li', 'h2', 'h3')), None)
        if card is None:
            card = next((node for node in parents if getattr(node, 'name', '') in ('div', 'section') and
                         re.search(r'(?:article|card|item|list|entry|headline|story)',
                                   ' '.join(node.get('class', [])) + ' ' + str(node.get('id', '')), re.I)), anchor)
        labels = ' '.join(str(node.get(attr, '')) for node in [card, *card.find_all()]
                          for attr in ('alt', 'aria-label', 'title'))
        has_badge = any(id(node) in blocked for node in card.find_all())
        if has_badge or (terms and terms.search(card.get_text(' ', strip=True) + ' ' + labels)):
            denied_urls.update(filter_links([anchor['href']], base, domains, pattern))
            continue
        links.append(anchor['href'])
    return [url for url in filter_links(links, base, domains, pattern) if url not in denied_urls]


def require_links(links, name):
    if not links: raise ArticleExtractionError(name+'：未找到可识别的文章链接。')
    return links


def fetch_document(fetch, url, headers):
    """Ask the supplied downloader for a source-owned document profile.

    Lightweight test fetchers often only accept a URL, so retain that narrow
    compatibility path without changing the production downloader contract.
    """
    try:
        return fetch(url, headers=headers)
    except TypeError as error:
        if 'headers' not in str(error):
            raise
        return fetch(url)
