"""Closed request vocabulary shared by the worker and the network-only role."""

import hashlib
import hmac
import re
import time
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

SOURCES = {
    "apple": "Apple Books",
    "google": "Google Books",
    "openlibrary": "Open Library",
    "hardcover": "Hardcover",
    "goodreads": "Goodreads",
    "lexicanum_live": "Lexicanum (live)",
    "lexicanum": "Lexicanum (archived copy)",
    "paste": "Image URL",
}
STATES = {
    "not_configured",
    "partial",
    "results",
    "empty",
    "unavailable",
    "rate_limited",
    "timed_out",
    "failed",
    "challenged",
    "busy",
}

WIKI_HOSTS = (
    "wh40k.lexicanum.com",
    "whfb.lexicanum.com",
    "ageofsigmar.lexicanum.com",
    "catalogue.lexicanum.com",
)
GOODREADS_IMAGES = (
    "i.gr-assets.com",
    "images.gr-assets.com",
    "images-na.ssl-images-amazon.com",
    "m.media-amazon.com",
)
BROWSER_HOSTS = ("www.goodreads.com", "goodreads.com", *GOODREADS_IMAGES, *WIKI_HOSTS)
NON_ARTICLE_NAMESPACES = (
    "media",
    "special",
    "talk",
    "user",
    "user talk",
    "lexicanum",
    "lexicanum talk",
    "warhammer 40k",
    "warhammer 40k talk",
    "warhammer",
    "warhammer talk",
    "catalogue - lexicanum",
    "catalogue - lexicanum talk",
    "file",
    "file talk",
    "image",
    "image talk",
    "mediawiki",
    "mediawiki talk",
    "template",
    "template talk",
    "help",
    "help talk",
    "category",
    "category talk",
    "portal",
    "portal talk",
    "module",
    "module talk",
)


def browser_signature(secret, path, body, stamp):
    return hmac.new(
        secret.encode("ascii"),
        b"POST\n" + path.encode("ascii") + b"\n" + stamp.encode("ascii") + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()


def browser_authenticated(secret, path, body, stamp, signature, *, now=None):
    try:
        return (
            len(secret) >= 32
            and secret.isascii()
            and bool(re.fullmatch(r"[0-9]{1,12}", stamp))
            and abs((time.time() if now is None else now) - int(stamp)) <= 30
            and bool(re.fullmatch(r"[a-f0-9]{64}", signature))
            and hmac.compare_digest(signature, browser_signature(secret, path, body, stamp))
        )
    except (ValueError, TypeError, UnicodeError):
        return False


def browser_url(url, kind):
    if (
        type(url) is not str
        or not url.isascii()
        or len(url) > 4096
        or any(ord(c) <= 32 or ord(c) == 127 for c in url)
        or "\\" in url
    ):
        raise ValueError("Unsupported source address.")
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or p.hostname not in BROWSER_HOSTS
        or p.username is not None
        or p.password is not None
        or p.port not in (None, 443)
        or p.fragment
    ):
        raise ValueError("Unsupported source address.")
    path = unquote(p.path)
    if any(c in path for c in ("\\", "\x00")) or any(x in {".", ".."} for x in path.split("/")):
        raise ValueError("Unsupported source path.")
    if kind == "goodreads":
        valid = p.hostname in ("goodreads.com", "www.goodreads.com") and (
            (p.path == "/search" and set(parse_qs(p.query, keep_blank_values=True)) <= {"q"})
            or (
                bool(re.fullmatch(r"/book/show/[0-9]+[^/]*", p.path))
                and set(parse_qs(p.query, keep_blank_values=True))
                <= {"from_search", "from_srp", "qid", "rank"}
            )
        )
    elif kind == "lexicanum_search":
        params = parse_qs(p.query, keep_blank_values=True)
        valid = (
            p.hostname in WIKI_HOSTS
            and p.path == "/mediawiki/index.php"
            and set(params) == {"title", "search", "fulltext", "limit", "ns0"}
            and all(len(values) == 1 for values in params.values())
            and params["title"] == ["Special:Search"]
            and params["fulltext"] == ["1"]
            and params["limit"] == ["5"]
            and params["ns0"] == ["1"]
            and 0 < len(params["search"][0]) <= 600
            and not any(ord(c) < 32 or ord(c) == 127 for c in params["search"][0])
        )
    elif kind == "lexicanum":
        title = path.removeprefix("/wiki/")
        valid = (
            p.hostname in WIKI_HOSTS
            and path.startswith("/wiki/")
            and bool(title)
            and (
                ":" not in title
                or title.split(":", 1)[0].replace("_", " ").strip().lower()
                not in NON_ARTICLE_NAMESPACES
            )
            and "/" not in title
            and "%" not in title
            and not any(ord(c) < 32 or ord(c) == 127 for c in title)
            and not p.query
        )
    elif kind == "image":
        valid = not p.query and (
            (
                p.hostname in GOODREADS_IMAGES
                and (
                    p.hostname != "m.media-amazon.com"
                    or path.startswith("/images/S/compressed.photo.goodreads.com/books/")
                )
                and bool(re.search(r"\.(?:jpg|jpeg|png)$", path, re.IGNORECASE))
                and "nophoto" not in path.lower()
            )
            or (
                p.hostname in WIKI_HOSTS
                and bool(
                    re.fullmatch(
                        r"/mediawiki/images/[a-f0-9]/[a-f0-9]{2}/[^/]+\.(?:jpg|jpeg|png)",
                        path,
                        re.IGNORECASE,
                    )
                )
                and path.rsplit("/", 1)[-1].lower() != "book2.jpg"
            )
        )
    else:
        valid = False
    if not valid:
        raise ValueError("Unsupported source path.")
    return url


def query(value):
    if type(value) is not dict or set(value) != {"title", "author", "isbn"}:
        raise ValueError
    limits = {"title": 300, "author": 300, "isbn": 32}
    for k, maximum in limits.items():
        if (
            type(value[k]) is not str
            or len(value[k]) > maximum
            or any(ord(c) < 32 for c in value[k])
        ):
            raise ValueError
    if not value["title"].strip() and not value["isbn"].strip():
        raise ValueError
    if value["isbn"] and not re.fullmatch(r"[0-9Xx -]+", value["isbn"]):
        raise ValueError
    return {k: v.strip() for k, v in value.items()}


def request(value):
    if type(value) is not dict or set(value) != {"query", "sources", "request_id"}:
        raise ValueError
    q = query(value["query"])
    sources = value["sources"]
    if (
        type(sources) is not list
        or len(sources) != 1
        or type(sources[0]) is not str
        or sources[0] not in SOURCES
        or sources[0] == "paste"
    ):
        raise ValueError
    if (
        type(value["request_id"]) is not str
        or str(uuid.UUID(value["request_id"])) != value["request_id"]
    ):
        raise ValueError
    return q, sources[0]


IMAGE_HOSTS = {
    "apple": ("mzstatic.com",),
    "google": ("books.google.com", "books.googleusercontent.com"),
    "openlibrary": ("covers.openlibrary.org",),
    "hardcover": ("assets.hardcover.app",),
    "lexicanum": ("web.archive.org",),
}


def live_wiki_host(host):
    return bool(host) and (
        host.rstrip(".").lower() == "lexicanum.com"
        or host.rstrip(".").lower().endswith(".lexicanum.com")
    )


def image_url(url, source):
    from urllib.parse import urlsplit

    if type(source) is not str or source not in SOURCES or type(url) is not str:
        raise ValueError("Unknown image source.")
    if source in {"goodreads", "lexicanum_live"}:
        browser_url(url, "image")
        host = urlsplit(url).hostname
        if (source == "goodreads") != (host in GOODREADS_IMAGES):
            raise ValueError("Image host is not allowed for this source.")
        return url
    # Refuse non-ASCII rather than letting http.client crash on a Unicode path.
    if (
        not url.isascii()
        or len(url) > 4096
        or any(ord(c) <= 32 or ord(c) == 127 for c in url)
        or "\\" in url
    ):
        raise ValueError("Use an encoded HTTPS image address.")
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or not p.hostname
        or p.username is not None
        or p.password is not None
        or p.port not in (None, 443)
        or p.fragment
        or live_wiki_host(p.hostname)
    ):
        raise ValueError("Use a public HTTPS image address.")
    host = p.hostname.lower()
    if source != "paste" and not any(
        host == allowed or (source == "apple" and host.endswith("." + allowed))
        for allowed in IMAGE_HOSTS[source]
    ):
        raise ValueError("Image host is not allowed for this source.")
    return url


def image_request(value):
    if type(value) is not dict or set(value) != {"url", "source"}:
        raise ValueError
    image_url(value["url"], value["source"])
    return value
