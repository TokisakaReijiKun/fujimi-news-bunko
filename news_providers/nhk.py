"""NHK: newsweb article blocks and inline broadcast media."""
import requests
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse, urlencode
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
    scope=p.require_scope(soup,'.content--detail-body, .article-body, [itemprop="articleBody"]',NAME)
    p.reject_gate(scope,'[data-paywall="true"]')
    p.clean_scope(scope)
    # Recommendation cards are not broadcast story paragraphs or images.
    for node in list(scope.select('[class*="related"], [class*="recommend"], [data-testid*="Related"]')): node.decompose()
    text,origins=p.paragraphs(scope.select('p, h2, h3, h4'),scope)
    pictures=p.images(scope.select('figure img, .article-image img, .content--detail-body img'),scope,origins,url)
    pictures=pictures or p.preview_image(soup,url)
    result=p.article_result(KEY,heading,records,text,pictures,p.direct_videos(scope,url))
    result['paragraph_kinds']=['heading-'+n.name[1] if n.name in ('h2','h3','h4') else 'paragraph' for n in origins]
    return result


def fetch_article(url, fetch):
    blob,final=fetch(url)
    p.validate_article_url(final,DOMAINS,ARTICLE_PATH)
    soup,records=p.document(blob)
    if soup.select_one('script[id^="json-ld-"]') and not soup.select_one('.content--detail-body, .article-body, [itemprop="articleBody"]'):
        return _fetch_current(final,fetch,records)
    result=extract_page(blob,final);result['url']=final
    return result


def _marked_plain(text):
    """Narrow NHK markup normalization for checking the full-text counterpart."""
    text=re.sub(r'(?m)^:::.*$|^(?:\*{3,}|-{3,})\s*$','',text)
    text=re.sub(r'!\[([^\]]*)\]\([^\n]*?\)',r'\1',text)
    text=re.sub(r'(?m)^#{1,6}\s+','',text)
    text=re.sub(r'(?<!!)\[([^\]]+)\]\(https?://[^\s)]+\)',r'\1',text)
    return re.sub(r'\s+','',text.replace('**','').replace('\\\n','\n'))


def _marked_body(marked):
    text,kinds,pictures=[],[],[]
    pending=[];containers=[]
    def flush():
        value='\n'.join(pending).strip();pending.clear()
        if value:
            text.append(value);kinds.append('paragraph')
    for raw in marked.splitlines():
        line=raw.strip()
        if line.startswith(':::'):
            flush()
            if line==':::':
                if not containers:raise p.ArticleExtractionError('NHK 正文容器不完整。')
                containers.pop()
            else:
                containers.append(line.startswith(':::nw--link-'))
            continue
        if any(containers):continue
        if not line or re.fullmatch(r'\*{3,}|-{3,}',line):
            flush();continue
        heading=re.fullmatch(r'(#{1,6})\s+(.+)',line)
        image=re.fullmatch(r'!\[([^\]]*)\]\((https?://[^\s)]+)\)',line)
        if heading:
            flush();text.append(heading[2]);kinds.append('heading-'+str(max(2,len(heading[1]))));continue
        if image:
            flush();src=image[2]
            if urlparse(src).scheme!='https' or not p.host_matches(src,('web.nhk','nhk.or.jp')):
                raise p.ArticleExtractionError('NHK 正文图片地址未通过来源验证。')
            pictures.append(dict(url=src,caption=image[1],link=src,position=len(text)))
            continue
        # Text remains plain; never run raw HTML or source-supplied styles.
        line=re.sub(r'(?<!!)\[([^\]]+)\]\(https?://[^\s)]+\)',r'\1',line)
        pending.append(line.replace('**','').removesuffix('\\'))
    flush()
    if containers:raise p.ArticleExtractionError('NHK 正文容器未闭合。')
    return text,kinds,pictures


def _api_article(data, url):
    aid=urlparse(url).path.rsplit('/',1)[-1]
    if (data.get('type')!='NewsArticle' or data.get('id')!=aid
            or data.get('canonical','').rstrip('/')!=url.rstrip('/')):
        raise p.ArticleExtractionError('NHK 正文归属不匹配，已停止收录。')
    p.reject_paid_metadata([data])
    body=data.get('articleBody','')
    if not isinstance(body,str) or not body.strip():
        raise p.ArticleExtractionError('NHK 只返回摘要，未取得完整正文，已停止收录。')
    detail=data.get('detailedArticleBody',{})
    marked='\n\n'.join(detail.get(k,'') for k in ('markedLead','markedBody'))
    if marked.strip():
        if _marked_plain(marked)!=_marked_plain(body):
            raise p.ArticleExtractionError('NHK 格式正文与全文不一致，已停止收录。')
        text,kinds,inline_pictures=_marked_body(marked)
    else:
        text=[part.strip() for part in re.split(r'\n\s*\n',body) if part.strip()]
        kinds=['paragraph']*len(text);inline_pictures=[]
    if not text or sum(map(len,text))>150000:raise p.ArticleExtractionError('NHK 正文为空或过长。')
    pictures=[]
    image=data.get('image',{}).get('medium',{})
    if image.get('url'):
        pictures.append(dict(url=image['url'],caption=image.get('caption',''),link=image['url'],position=-1))
    pictures.extend(inline_pictures)
    videos=[]
    for video in data.get('video',[]):
        for content in video.get('detailedContent',[]):
            src=content.get('contentUrl','')
            if (urlparse(src).scheme=='https' and p.host_matches(src,('nhk','nhk.or.jp'))
                    and urlparse(src).path.endswith(('.m3u8','.mp4')) and src not in videos):videos.append(src)
    result=p.article_result(KEY,p.plain(data.get('headline')), [data],text,pictures,videos)
    result.update(url=url,paragraph_kinds=kinds)
    return result


def _fetch_current(url, fetch, records):
    p.reject_paid_metadata(records)
    aid=urlparse(url).path.rsplit('/',1)[-1]
    api='https://api.web.nhk/r8/t/newsarticle/na/'+aid+'.json'
    with requests.Session() as session:
        blob,_=fetch(api,session=session)
        data=json.loads(blob)
        if not data.get('articleBody'):
            _authorize_overseas(url,fetch,session)
            blob,_=fetch(api,session=session);data=json.loads(blob)
        return _api_article(data,url)


def _authorize_overseas(url, fetch, session):
    # Official anonymous overseas flow; no domestic subscription claim.
    blob,_=fetch('https://location.tools.nhk/geoip/area.json',session=session)
    location=json.loads(blob)
    if not location.get('country_name') or location['country_name']=='Japan':
        raise p.ArticleExtractionError('NHK 需要原站阅读授权，当前仅取得摘要。')
    query=urlencode(dict(idp='a-alaz',profileType='abroad',redirect_uri=url,
                         entity='none',area='130',pref='13',jisx0402='13101',postal='1000001'))
    _,final=fetch('https://news.web.nhk/tix/build_authorize?'+query,session=session)
    if final.rstrip('/')!=url.rstrip('/'):
        raise p.ArticleExtractionError('NHK 海外阅读确认未完成。')


def _resolve_videos(extracted, services):
    result=dict(extracted,videos=list(extracted.get('videos',[])),media_warnings=list(extracted.get('media_warnings',[])))
    protected=[u for u in result['videos'] if urlparse(u).hostname=='media.vd.st.nhk']
    if not protected:return result
    services.reset_budget();services.check()
    services.stage('media','NHKニュース：获取原站短期播放授权',60)
    try:
        with requests.Session() as session:
            _authorize_overseas(extracted['url'],services.download,session)
            key=next((c.value for c in session.cookies if c.name=='z_at' and c.domain.lstrip('.')=='web.nhk'),None)
            if not key:raise ValueError('未取得匿名会话')
            blob,_=services.download('https://mediatoken.web.nhk/v1/token',
                                     headers={'Authorization':'Bearer '+key},session=session,max_bytes=1024*1024)
            token=json.loads(blob).get('token','')
            if not token.startswith('exp='):raise ValueError('播放授权无效')
            result['videos']=[u+'?'+urlencode({'hdnts':token}) if u in protected else u for u in result['videos']]
    except services.cancelled_error:raise
    except Exception:
        result['videos']=[u for u in result['videos'] if u not in protected]
        result['media_warnings'].append('NHK 视频未下载：原站播放授权失败。')
    finally:services.reset_budget()
    return result


def postprocess(article, extracted, services):
    # NHK media belongs to the report; save it before waiting for translation.
    result=services.prepare(article,extracted,KEY)
    services.annotate(result)
    services.save(result)
    resolved=_resolve_videos(extracted,services)
    if any(urlparse(i.get('url','')).hostname=='img.web.nhk' for i in resolved.get('images',[])):
        services.reset_budget();services.check()
        services.stage('media','NHKニュース：获取正文图片阅读授权',60)
        with requests.Session() as session:
            _authorize_overseas(extracted['url'],services.download,session)
            def image_download(url,**kwargs):
                if urlparse(url).hostname=='img.web.nhk':kwargs['session']=session
                return services.download(url,**kwargs)
            result=services.media(result,resolved,seconds=120,download=image_download)
    else:
        result=services.media(result,resolved,seconds=120)
    services.translate(result,seconds=90)
    return services.save(result)


def retranslate(article, services):
    article['failure_reason']=''
    services.translate(article,seconds=90,force=True)
    result=services.save(article)
    if result.get('failure_reason'):
        raise ValueError(result['failure_reason'])
    return result
