"""Sankei: article-text paragraphs with article-image figure captions."""
from . import primitives as p

KEY = 'sankei'
NAME = '産経新聞'
DOMAINS = ('sankei.com',)
ARTICLE_PATH = r'/article/\d{8}-[A-Z0-9]+/?'
PAID_BADGES = ('img[alt="有料会員記事"]', 'img[src*="/img_lock-gold.svg"]')


def html_links(blob, base):
    return p.public_listing_links(
        blob, base, DOMAINS, ARTICLE_PATH,
        member_selectors=('[data-paywall="true"]', '[data-testid="paywall"]', '[class*="premium"]', '.paid_members', *PAID_BADGES),
        member_terms=('会員限定', '有料記事', '有料会員記事', '産経電子版'))


def collect(source, fetch):
    blob,base=fetch(source['homepage'])
    return p.require_links(html_links(blob,base),NAME)


def extract_page(blob, url):
    p.validate_article_url(url,DOMAINS,ARTICLE_PATH)
    soup,records=p.document(blob)
    p.reject_paid_metadata(records)
    article=p.require_scope(soup,'article.article-wrapper',NAME)
    header=article.select_one('.article-header, header')
    if ('paid_members' in article.get('class',[]) or
            (header and header.select_one(','.join(PAID_BADGES)))):
        raise p.PaidArticleError('産経本文标记为有料会員記事，未收录。')
    p.reject_gate(soup.select_one('main') or soup,'article.article-wrapper.premium, [data-paywall="true"]')
    heading=p.title(soup,records,excluded=('産経ニュース',))
    scope=p.require_scope(soup,'article.article-wrapper .article-body',NAME)
    p.clean_scope(scope)
    text,origins=p.paragraphs(scope.select('p.article-text, h2.article-text, h3.article-text, h2, h3'),scope,
                              exclude=('◇', '◇ '))
    pictures=p.images(scope.select('figure.article-image img'),scope,origins,url) or p.preview_image(soup,url)
    result=p.article_result(KEY,heading,records,text,pictures,p.direct_videos(scope,url))
    # Keep the kind aligned with accepted paragraphs after noise removal.
    result['paragraph_kinds']=['heading-'+node.name[1] if node.name in ('h2','h3') else 'paragraph'
                               for node in origins]
    return result


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
