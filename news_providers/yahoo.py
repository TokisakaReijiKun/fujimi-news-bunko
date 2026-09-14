"""Yahoo News owns pickup resolution, same-story pagination and postprocessing."""
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
import re
from . import primitives as p

KEY='yahoo'
NAME='Yahoo!ニュース'
DOMAINS=('news.yahoo.co.jp',)
ARTICLE_PATH=r'/(?:articles/[a-f0-9]{40}|pickup/\d+)/?'
BODY_PATH=r'/articles/[a-f0-9]{40}/?'


def html_links(blob, base):
    return p.public_listing_links(blob, base, DOMAINS, ARTICLE_PATH)


def collect(source, fetch):
    blob,base=fetch(source['homepage'])
    return p.require_links(html_links(blob,base),NAME)


def resolve_pickup(blob, url):
    if not p.host_matches(url,DOMAINS) or not urlparse(url).path.startswith('/pickup/'): return None
    soup,_=p.document(blob)
    for anchor in soup.select('a[href]'):
        if '記事全文を読む' not in anchor.get_text(): continue
        link=urljoin(url,anchor['href'])
        if p.host_matches(link,DOMAINS) and re.fullmatch(BODY_PATH,urlparse(link).path):
            return urlunparse(urlparse(link)._replace(query='',fragment=''))
    raise p.ArticleExtractionError('Yahoo!ニュースの本文リンクが見つかりません。')


def photo_caption(img):
    figure=img.find_parent('figure')
    if figure and figure.select_one('figcaption'): return figure.select_one('figcaption')
    parent=img.find_parent('a') or img.parent
    if parent and parent.parent:
        caption=parent.parent.find('p')
        if caption and 'yjSlinkDirectlink' not in caption.get('class',[]): return caption
    return None


def extract_page(blob, url):
    p.validate_article_url(url,DOMAINS,BODY_PATH)
    soup,records=p.document(blob)
    p.reject_paid_metadata(records)
    p.reject_gate(soup.select_one('article#uamods') or soup,'[data-paywall="true"], [data-testid="paywall"]')
    heading=p.title(soup,records,selector='article#uamods h1',excluded=('Yahoo!ニュース',))
    scope=p.require_scope(soup,'article#uamods .article_body',NAME)
    p.clean_scope(scope)
    # Yahoo places photo/article recommendations beside the story body. Remove
    # their structural containers; never identify a recommendation by title.
    for node in list(scope.select('aside, [class*="related"], [class*="recommend"], [data-testid*="related"]')):
        node.decompose()
    paragraph_nodes = []
    for node in scope.select('p.yjSlinkDirectlink, h2, h3, h4'):
        # Yahoo marks cross-story/photo recommendations on the anchor itself.
        # A recommendation can share a <p> with the opening paragraph.
        # Remove only marked links, preserving the surrounding report text.
        related = node.select('a[data-cl-params*="_cl_vmodule:related"], '
                                  'a[data-cl-params*="_cl_link:photo"]')
        for link in related:
            link.decompose()
        paragraph_nodes.append(node)
    text,origins=p.paragraphs(paragraph_nodes,scope,split_blank_lines=True)
    photo_nodes=[img for img in scope.select('img') if any(token in img.get('src','')+img.get('data-src','') for token in ('newsatcl','amd-img'))]
    pictures=p.images(photo_nodes,scope,origins,url,caption_for=photo_caption) or p.preview_image(soup,url)
    videos=p.direct_videos(scope,url)
    warnings=['原站视频需动态播放器，当前仅保存可获取的预览图；视频请在原站观看。'] if not videos and b'yvpub/player' in blob else []
    result=p.article_result(KEY,heading,records,text,pictures,videos,warnings=warnings)
    result['paragraph_kinds']=['heading-'+node.name[1] if node.name in ('h2','h3','h4') else 'paragraph' for node in origins]
    raw_page=parse_qs(urlparse(url).query).get('page',['1'])[0]
    if not raw_page.isdigit(): raise p.ArticleExtractionError('Yahoo 分页页码无效。')
    for anchor in soup.select('a[href]'):
        candidate=urlparse(urljoin(url,anchor['href']))
        if candidate.hostname!=urlparse(url).hostname or candidate.path!=urlparse(url).path: continue
        page=parse_qs(candidate.query).get('page',[''])[0]
        if page.isdigit() and int(page)==int(raw_page)+1:
            result['next_url']=urlunparse(candidate._replace(query=urlencode({'page':page}),fragment=''))
            break
    return result


def fetch_article(url, fetch):
    if urlparse(url).path.startswith('/articles/'): url=urlunparse(urlparse(url)._replace(query='',fragment=''))
    blob,final=fetch(url)
    resolved=resolve_pickup(blob,final)
    if resolved: blob,final=fetch(resolved)
    result=extract_page(blob,final)
    result['url']=urlunparse(urlparse(final)._replace(query='',fragment=''))
    seen={final}
    while result['next_url']:
        next_url=result['next_url']
        if next_url in seen or len(seen)>=20: raise p.ArticleExtractionError('Yahoo 分页循环或超过 20 页，未保存不完整文章。')
        seen.add(next_url)
        blob,page_url=fetch(next_url)
        actual,expected=urlparse(page_url),urlparse(next_url)
        if actual.hostname!=urlparse(final).hostname or actual.path!=urlparse(final).path:
            raise p.ArticleExtractionError('Yahoo 分页重定向离开了原文章，未保存不完整文章。')
        if parse_qs(actual.query).get('page',['1'])!=parse_qs(expected.query).get('page',['1']):
            raise p.ArticleExtractionError('Yahoo 分页返回了错误页码，未保存不完整文章。')
        page=extract_page(blob,page_url)
        offset=len(result['paragraphs']);result['paragraphs'].extend(page['paragraphs'])
        result.setdefault('paragraph_kinds',[]).extend(page.get('paragraph_kinds', ['paragraph']*len(page['paragraphs'])))
        for image in page['images']:
            if image['url'] not in {i['url'] for i in result['images']}:
                image['position']=offset+max(0,image['position']);result['images'].append(image)
        result['videos'] += [v for v in page['videos'] if v not in result['videos']]
        result['media_warnings'] += [v for v in page['media_warnings'] if v not in result['media_warnings']]
        result['next_url']=page['next_url']
    return result


def postprocess(article, extracted, services):
    # Do not persist or translate until fetch_article validates every page.
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
