"""Publisher homepages recovered from the APK, with current NHK canonical URL."""
from news_providers import PROVIDERS, provider_for, custom, yahoo


PUBLISHERS = (
    ('NHKニュース', 'https://news.web.nhk/newsweb/'),
    ('朝日新聞', 'https://www.asahi.com/'),
    ('読売新聞', 'https://www.yomiuri.co.jp/'),
    ('日本経済新聞', 'https://www.nikkei.com/'),
    ('産経新聞', 'https://www.sankei.com/'),
    ('Yahoo!ニュース', 'https://news.yahoo.co.jp/'),
)


def publisher_key(url):
    module = provider_for(url)
    return None if module is custom else module.KEY


def default_sources():
    return [dict(id=i, name=name, homepage=url, minimum_count=1, voice_mode='browser', voice_id=None)
            for i, (name, url) in enumerate(PUBLISHERS, 1)]


def upgrade_sources(existing):
    """One-time repair: preserve IDs, quotas, voice choices and unrelated sources."""
    result = [dict(source) for source in existing]
    for default in default_sources():
        key = publisher_key(default['homepage'])
        match = next((s for s in result if publisher_key(s.get('homepage', '')) == key
                      or s.get('name') == default['name']), None)
        if match:
            match.update(name=default['name'], homepage=default['homepage'])
        else:
            default['id'] = max((s['id'] for s in result), default=0) + 1
            result.append(default)
    return result


ARTICLE_PATHS = {module.KEY: module.ARTICLE_PATH for module in PROVIDERS}


def html_article_links(blob, base_url):
    return provider_for(base_url).html_links(blob,base_url)


def collect_source_links(source, fetch, *, allow_alternate=True):
    collected = provider_for(source['homepage']).collect(source,fetch)
    # Legacy callers ask for links only. Providers may now return already
    # validated public candidates during their collection phase.
    return [item['url'] if isinstance(item, dict) else item for item in collected]


def yahoo_article_url(blob, url):
    return yahoo.resolve_pickup(blob,url)
