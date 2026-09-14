"""Nikkei: reject the main article paywall; never translate a member-only teaser."""
import json
import re
from bs4 import NavigableString
from urllib.parse import urlparse, parse_qs, urljoin
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


def _formatted_body(scope):
    """Keep Nikkei's boxed text, heading levels and explicit bold spans."""
    nodes = scope.select('p[class*="paragraph_"], h2, h3, div.container_c1tzahnc')
    values, origins, kinds, formats, seen = [], [], [], [], set()
    for node in nodes:
        if p.is_noise(node, scope) or node.find_parent('a'):
            continue
        box = node if 'container_c1tzahnc' in node.get('class',[]) else node.parent.parent if node.name in ('h2', 'h3') else None
        if (box is not None and box is not scope and box.name == 'div'
                and box.find('br', recursive=False)):
            node = box
        if id(node) in seen or any(id(parent) in seen for parent in node.parents):
            continue
        seen.add(id(node))
        kind = 'box' if node is box else 'heading-' + node.name[1] if node.name in ('h2', 'h3') else 'paragraph'
        if kind == 'box' and not node.select_one('h2,h3'):
            kind = 'box-plain'
        pieces = []
        def walk(child, bold=False):
            if isinstance(child, NavigableString):
                pieces.append((str(child).replace('\r', ''), bold))
            elif child.name == 'br':
                pieces.append(('\n' if kind in ('box','box-plain') else ' ', False))
            elif child.name not in ('rt', 'rp', 'script', 'style', 'iframe'):
                for item in child.children:
                    walk(item, bold or child.name in ('b', 'strong', 'h2', 'h3'))
        walk(node)
        raw = ''.join(text for text, _ in pieces)
        text = raw.strip()
        if not text:
            continue
        offset = len(raw) - len(raw.lstrip())
        spans, cursor = [], 0
        for part, bold in pieces:
            start, end = max(0, cursor-offset), min(len(text), cursor+len(part)-offset)
            if bold and end > start:
                if spans and spans[-1][1] == start:
                    spans[-1][1] = end
                else:
                    spans.append([start, end])
            cursor += len(part)
        values.append(text); origins.append(node); kinds.append(kind); formats.append(spans)
    if not values or sum(map(len, values)) > 150000:
        raise p.ArticleExtractionError('日经正文为空或过长，已停止导入。')
    return values, origins, kinds, formats


def _player_url(value):
    parsed = urlparse(value)
    return (parsed.scheme == 'https' and parsed.netloc == 'players.brightcove.net'
            and re.fullmatch(r'/4504957054001/[A-Za-z0-9_-]+/index.html', parsed.path)
            and re.fullmatch(r'\d+', parse_qs(parsed.query).get('videoId', [''])[0]))


def _resolve_videos(extracted, services):
    result=dict(extracted, videos=list(extracted.get('videos',[])),
                media_warnings=list(extracted.get('media_warnings',[])))
    for player in extracted.get('video_embeds',[])[:5]:
        if not _player_url(player):
            continue
        services.reset_budget();services.check()
        services.stage('media','日本経済新聞：解析原站视频文件',60)
        try:
            blob,_=services.download(player,max_bytes=2*1024*1024)
            match=re.search(r'"policy_key"\s*:\s*"([^"\r\n]+)"',blob.decode('utf-8'))
            if not match:match=re.search(r'policyKey\s*:\s*"([^"\r\n]+)"',blob.decode('utf-8'))
            if not match:raise ValueError('播放器配置缺少公开读取参数')
            video_id=parse_qs(urlparse(player).query)['videoId'][0]
            blob,_=services.download('https://edge.api.brightcove.com/playback/v1/accounts/4504957054001/videos/'+video_id,
                                     headers={'Accept':'application/json;pk='+match[1]},max_bytes=2*1024*1024)
            info=json.loads(blob)
            if str(info.get('id')) != video_id:raise ValueError('视频归属不匹配')
            sources=[s for s in info.get('sources',[]) if s.get('src','').startswith('https://')
                     and s.get('container')=='MP4' and not s.get('key_systems')
                     and 0 < s.get('size',0) <= 32*1024*1024]
            if not sources:raise ValueError('没有符合本地保存限制的公开 MP4')
            result['videos'].append(max(sources,key=lambda s:s['size'])['src'])
            if len(extracted.get('video_embeds',[])) == 1:
                result['media_title']=p.plain(info.get('name'))
                poster=info.get('poster','')
                if isinstance(poster,str) and poster.startswith('https://'):
                    # Replace only the social preview; keep actual body figures.
                    pictures=list(result.get('images',[]))
                    if len(pictures)==1 and pictures[0].get('position')==-1 and not pictures[0].get('caption'):
                        result['images']=[dict(url=poster,caption='',link=poster,position=-1)]
        except services.cancelled_error:
            raise
        except Exception:
            result['media_warnings'].append('日经视频文件解析失败，尚未下载；请稍后重试。')
        finally:services.reset_budget()
    return result


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
    article=p.require_scope(soup,'main#main-content > article, main#main-content article',NAME)
    heading=p.title(soup,records,selector='main#main-content article h1')
    scope=article.select_one('[data-track-article-content]') or article
    p.clean_scope(scope)
    text,origins,kinds,formats=_formatted_body(scope)
    pictures=p.images(scope.select('figure:not([data-optimizely-selector]) img'),scope,origins,url) or p.preview_image(soup,url)
    videos=p.direct_videos(scope,url)
    embeds=[value for value in videos if _player_url(value)]
    result=p.article_result(KEY,heading,records,text,pictures,
                            [value for value in videos if re.search(r'\.(mp4|webm)$',urlparse(value).path,re.I)])
    result.update(paragraph_kinds=kinds, paragraph_formats=formats, video_embeds=embeds)
    links=[]
    for paragraph,origin in zip(text,origins):
        items=[];cursor=0
        for anchor in origin.select('a[href]'):
            label=anchor.get_text('',strip=False)
            start=paragraph.find(label,cursor) if label else -1
            target=urljoin(url,anchor['href']);parsed=urlparse(target)
            if start<0:continue
            cursor=start+len(label)
            if parsed.scheme in ('https','http') and parsed.hostname and not parsed.username and not parsed.password:
                items.append({'start':start,'end':cursor,'url':target})
        links.append(items)
    result['paragraph_links']=links
    return result


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
    resolved=_resolve_videos(extracted,services)
    if resolved.get('media_title'):
        result['media_title']=resolved['media_title']
        services.save(result)
    return services.media(result,resolved,seconds=300)


def retranslate(article, services):
    article['failure_reason']=''
    services.translate(article,seconds=90,force=True)
    result=services.save(article)
    if result.get('failure_reason'):
        raise ValueError(result['failure_reason'])
    return result
