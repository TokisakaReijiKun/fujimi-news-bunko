"""Compatibility entry points; publisher modules own collection and parsing."""
from news_providers import provider_for
from news_providers.primitives import (
    ArticleExtractionError, PaidArticleError, metadata, schema_nodes, plain,
)


def extract_page(blob, url):
    return provider_for(url).extract_page(blob,url)


def fetch_article(url, fetch):
    return provider_for(url).fetch_article(url,fetch)
