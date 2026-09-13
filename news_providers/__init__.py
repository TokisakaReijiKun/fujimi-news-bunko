"""Route by the original URL, never by downloaded text or an article's title."""
from . import nhk, asahi, yomiuri, nikkei, sankei, yahoo, custom
from .primitives import host_matches

PROVIDERS=(nhk,asahi,yomiuri,nikkei,sankei,yahoo)


def provider_for(url):
    return next((module for module in PROVIDERS if host_matches(url,module.DOMAINS)),custom)
