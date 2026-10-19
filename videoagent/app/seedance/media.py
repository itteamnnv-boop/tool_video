"""Provider master URL resolution; never treat a preview URL rewrite as proof."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def is_watermarked_url(url):
    parts = urlsplit(str(url))
    query = dict(parse_qsl(parts.query))
    return (bool(re.search(r"video_gen_watermark|/(?:wm|watermark)(?:/|_)", parts.path, re.I))
            or query.get("lr", "").lower() == "watermarked"
            or query.get("logo_type", "").lower() in ("watermarked", "wm")
            or query.get("water_mark", "") == "1")


def master_api_url(url):
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in ("channel", "codec_type", "logo_type")]
    pairs.extend((("channel", "no"), ("codec_type", "8"), ("logo_type", "unwatermarked")))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def url_is_master(url):
    query = dict(parse_qsl(urlsplit(url).query))
    return any(query.get(k, "").lower() == "unwatermarked" for k in ("logo_type", "lr"))
