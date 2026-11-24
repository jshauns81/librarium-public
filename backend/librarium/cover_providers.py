"""LF provider algorithms with Librarium bounded transport and truthful failures.
See cover_sources_provenance.json. No library, writer or database imports.
"""

import html
import json
import os
import re
import threading
import time
import urllib.parse
from typing import Any

from librarium.cover_source_fetch import SourceFailure, fetch, query_url
from librarium.cover_source_rules import apple_hires, english_isbn, isbn13, norm, similarity

HC_TOKEN = os.environ.get("HARDCOVER_TOKEN", "").strip()
HC_ISBN = "query($isbn:String!){ editions(where:{_or:[{isbn_13:{_eq:$isbn}},{isbn_10:{_eq:$isbn}}]},limit:3){\n  title image{url} book{ title image{url} contributions(limit:3){author{name}} } } }"
HC_SEARCH = 'query($q:String!){ search(query:$q, query_type:"Book", per_page:5){ results } }'
LX_WIKIS = ["wh40k.lexicanum.com", "ageofsigmar.lexicanum.com", "whfb.lexicanum.com"]
LX_WEAK = 0.75
LX_DEADLINE = 75
LX_PUB = (
    "novel",
    "audio drama",
    "short story",
    "novella",
    "anthology",
    "audiobook",
    "omnibus",
    "graphic novel",
    "book",
    "game book",
    "background book",
)
LX_NO_COVER = {"Book2.jpg"}
WB_BACKOFF = 20 * 60
WB = "https://web.archive.org"
_lx_cache: dict[tuple, tuple] = {}
_host_next: dict[str, float] = {}
_wb_state = {"until": 0.0}
_lx_tl = threading.local()
_lx_bg, _host_lock = threading.Lock(), threading.Lock()
_HOST_GAP = {
    "itunes.apple.com": 3.1,
    "www.googleapis.com": 1.0,
    "openlibrary.org": 0.6,
    "covers.openlibrary.org": 0.3,
    "web.archive.org": 5.0,
}
_deadline = threading.local()


class Reply:
    def __init__(self, raw, status=200):
        self.content, self.status_code, self.headers = raw, status, {}
        self.text = raw.decode("utf-8", "replace")
        self.ok = status == 200

    def json(self):
        return json.loads(self.content)


class Transport:
    def get(self, url, timeout=12, params=None, **kw):
        return Reply(
            fetch(
                query_url(url, params),
                maximum=1024 * 1024,
                seconds=timeout,
                deadline=getattr(_deadline, "at", None),
                follow_redirects=not bool((params or {}).get("key")),
            )
        )

    def post(self, url, timeout=12, headers=None, json=None):
        raw = fetch(
            url,
            maximum=1024 * 1024,
            seconds=timeout,
            method="POST",
            payload=json,
            token=(headers or {}).get("authorization"),
            deadline=getattr(_deadline, "at", None),
        )
        value = Reply(raw)
        if value.json().get("errors"):
            raise SourceFailure("unavailable")
        return value


S = Transport()


def log(*args):
    pass  # Provider errors and query text never enter service logs.


def _get(url, timeout=12, **kw):
    _pace(url)
    return S.get(url, timeout=timeout, **kw)


def _lx_raw(url, timeout=15, **kw):
    _pace(url)
    remaining = getattr(_lx_tl, "deadline", float("inf")) - time.time()
    if remaining <= 0:
        raise SourceFailure("timed_out")
    previous = getattr(_deadline, "at", None)
    _deadline.at = min(previous or float("inf"), time.monotonic() + remaining)
    try:
        return S.get(url, timeout=min(timeout, remaining), **kw)
    finally:
        _deadline.at = previous


def _pace(url):
    host = urllib.parse.urlparse(url).hostname or ""
    gap = _HOST_GAP.get(host)
    if not gap:
        return
    with _host_lock:
        now = time.time()
        at = max(now, _host_next.get(host, 0))
        remaining = (
            min(
                getattr(_deadline, "at", None) or float("inf"),
                time.monotonic() + getattr(_lx_tl, "deadline", float("inf")) - now,
            )
            - time.monotonic()
        )
        if at - now >= remaining:
            raise SourceFailure("timed_out")
        _host_next[host] = at + gap
    if at > now:
        time.sleep(at - now)


def src_apple(title, author, isbn):
    res: list[dict[str, Any]] = []
    by_isbn = False
    if isbn:
        r = _get("https://itunes.apple.com/lookup", params={"isbn": isbn})
        res = (r.json().get("results") if r else None) or []
        by_isbn = bool(res)
    if not res and title:
        r = _get(
            "https://itunes.apple.com/search",
            params={"term": f"{title} {author}".strip(), "entity": "ebook", "limit": 6},
        )
        res = (r.json().get("results") if r else None) or []
    return [
        {
            "src": "Apple Books",
            "urls": apple_hires(it["artworkUrl100"]),
            "title": it.get("trackName", ""),
            "author": it.get("artistName", ""),
            "by_isbn": by_isbn,
        }
        for it in res
        if it.get("artworkUrl100")
    ]


def src_google(title, author, isbn):
    q = (
        f"isbn:{isbn}"
        if isbn
        else " ".join(
            x
            for x in (
                f'intitle:"{title}"' if title else "",
                f'inauthor:"{author}"' if author else "",
            )
            if x
        )
    )
    params = {"q": q, "maxResults": 5}
    key = os.environ.get("GOOGLE_BOOKS_API_KEY", "").strip()
    if key:
        params["key"] = key
    r = _get("https://www.googleapis.com/books/v1/volumes", params=params)
    out = []
    for it in ((r.json().get("items") if r else None) or [])[:4]:
        vi = it.get("volumeInfo", {})
        if "imageLinks" in vi:
            ids = sorted(
                vi.get("industryIdentifiers") or [], key=lambda x: x.get("type") != "ISBN_13"
            )
            out.append(
                {
                    "src": "Google Books",
                    "title": vi.get("title", ""),
                    "author": ", ".join(vi.get("authors", [])),
                    "by_isbn": bool(isbn),
                    "isbn": english_isbn(x.get("identifier") for x in ids),
                    "urls": [
                        f"https://books.google.com/books/publisher/content/images/frontcover/{it['id']}?fife=w1600-h2400",
                        f"https://books.google.com/books/content?id={it['id']}&printsec=frontcover&img=1&zoom=0",
                    ],
                }
            )
    return out


def _ol_cover_urls(doc):
    urls: list[str] = []

    def add(kind, value):
        url = f"https://covers.openlibrary.org/b/{kind}/{value}-L.jpg?default=false"
        if url not in urls and len(urls) < 3:
            urls.append(url)

    editions = doc.get("editions")
    docs = editions.get("docs") if isinstance(editions, dict) else None
    for item in [doc] + (docs if isinstance(docs, list) else [])[:3]:
        if not isinstance(item, dict):
            continue
        value = item.get("cover_i")
        if type(value) is int and value > 0:
            add("id", value)
        edition = item.get("cover_edition_key") or item.get("key", "")
        if type(edition) is str:
            edition = edition.removeprefix("/books/")
            if re.fullmatch(r"OL[0-9]+M", edition):
                add("olid", edition)
    identifier = next((n for v in (doc.get("isbn") or []) if (n := isbn13(v))), None)
    if identifier:
        add("isbn", identifier)
    return urls


def src_openlibrary(title, author, isbn):
    out = []
    if isbn:
        out.append(
            {
                "src": "Open Library",
                "title": title,
                "author": author,
                "by_isbn": True,
                "urls": [f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"],
            }
        )
    if title:
        r = _get(
            "https://openlibrary.org/search.json",
            params={
                "title": title,
                "author": author or None,
                "limit": 5,
                "fields": "title,author_name,cover_i,cover_edition_key,isbn,editions,editions.key,editions.cover_i",
            },
        )
        for d in (r.json().get("docs") if r else None) or []:
            urls = _ol_cover_urls(d)
            if urls:
                out.append(
                    {
                        "src": "Open Library",
                        "title": d.get("title", ""),
                        "author": ", ".join(d.get("author_name", [])[:2]),
                        "isbn": english_isbn(d.get("isbn")),
                        "urls": urls,
                    }
                )
    return out


def src_hardcover(title, author, isbn):
    if not HC_TOKEN:
        raise SourceFailure("not_configured")
    auth = {
        "authorization": HC_TOKEN
        if HC_TOKEN.lower().startswith("bearer ")
        else f"Bearer {HC_TOKEN}"
    }
    out = []
    try:
        if isbn:
            r = S.post(
                "https://api.hardcover.app/v1/graphql",
                timeout=12,
                headers=auth,
                json={"query": HC_ISBN, "variables": {"isbn": isbn}},
            )
            for e in (r.json().get("data") or {}).get("editions", []) if r.ok else []:
                b = e.get("book") or {}
                who = ", ".join(
                    c["author"]["name"] for c in b.get("contributions", []) if c.get("author")
                )
                for img in (e.get("image"), b.get("image")):
                    if img and img.get("url"):
                        out.append(
                            {
                                "src": "Hardcover",
                                "urls": [img["url"]],
                                "title": e.get("title") or b.get("title", ""),
                                "author": who,
                                "by_isbn": True,
                            }
                        )
        if title and not out:
            r = S.post(
                "https://api.hardcover.app/v1/graphql",
                timeout=12,
                headers=auth,
                json={"query": HC_SEARCH, "variables": {"q": f"{title} {author}".strip()}},
            )
            results = (
                ((r.json().get("data") or {}).get("search") or {}).get("results") if r.ok else None
            )
            if isinstance(results, str):
                results = json.loads(results)
            hits = (results or {}).get("hits") or []
            for h in hits:
                d = h.get("document", {})
                if (d.get("image") or {}).get("url"):
                    out.append(
                        {
                            "src": "Hardcover",
                            "urls": [d["image"]["url"]],
                            "title": d.get("title", ""),
                            "author": ", ".join(d.get("author_names", [])[:2]),
                            "isbn": english_isbn(d.get("isbns")),
                        }
                    )
    except SourceFailure:
        raise
    except ValueError, KeyError, TypeError:
        raise SourceFailure("failed") from None
    return out


def _lx_variants(title):
    t = re.sub(r"\s+", " ", title or "").strip()
    out = [t]
    for sep in (":", " - ", " – "):
        if sep in t:
            out += [x.strip() for x in t.split(sep) if len(x.strip()) >= 4]
    seen, res = set(), []
    for v in out:
        if v.lower() not in seen:
            seen.add(v.lower())
            res.append(v)
    return res[:3]


def _lx_text(frag):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", frag))).strip()


def lx_infobox(page):
    """Publication infobox of a Lexicanum article -> {img, thumb, caption, caption_links, author} or None.
    Character/faction pages have no Author row, so they're rejected here."""
    i = page.find('id="mw-content-text"')
    body = page[i:] if i >= 0 else page
    for m in re.finditer(r"<table[^>]*>(.*?)</table>", body, re.DOTALL):
        t = m.group(1)
        f = re.search(
            r'<a href="/wiki/File:[^"]*" class="image"><img [^>]*?src="([^"]+)"[^>]*?/?>', t
        )
        a = re.search(
            r">\s*(?:<b>)?\s*Authors?(?:\(s\))?\s*(?:</b>)?\s*</t[dh]>\s*<t[dh][^>]*>(.*?)</t[dh]>",
            t,
            re.DOTALL,
        )
        if not f or not a:
            continue
        if os.path.basename(f.group(1)).split("px-")[-1] in LX_NO_COVER:
            return None  # the wiki's generic "no cover yet" book icon
        tag = f.group(0)
        src = html.unescape(f.group(1))
        ss = re.search(r'srcset="([^"]+)"', tag)
        full = None
        for part in html.unescape(ss.group(1)).split(",") if ss else []:
            u = part.strip().split(" ")[0]
            if "/thumb/" not in u:
                full = u
        if not full:
            mm = re.match(r"(.*/images)/thumb/(.+?)/[^/]+$", src)
            full = f"{mm.group(1)}/{mm.group(2)}" if mm else src
        cap = t[f.end() :]
        cap = cap[: cap.find("</td>")] if "</td>" in cap else cap[:400]
        links = [
            urllib.parse.unquote(x).replace("_", " ")
            for x in re.findall(r'href="/wiki/(?!File:)([^"#]+)"', cap)
        ]
        return {
            "img": full,
            "thumb": src,
            "caption": _lx_text(cap),
            "caption_links": links,
            "author": re.sub(r"\s*\[\d+\]", "", _lx_text(a.group(1))),
        }
    return None


def _lx_retry_pause():
    if getattr(_lx_tl, "deadline", float("inf")) - time.time() <= 3:
        raise SourceFailure("timed_out")
    if (getattr(_deadline, "at", None) or float("inf")) - time.monotonic() <= 3:
        raise SourceFailure("timed_out")
    time.sleep(3)


def _wb(url, **kw):
    """Wayback Machine GET with one retry (it drops the odd request or briefly answers 'Temporarily
    Offline'). A 429 pauses every Wayback request for WB_BACKOFF; such lookups are flagged incomplete
    so the pre-bake retries them later instead of recording "nothing found"."""
    for attempt in (0, 1):
        if time.time() < _wb_state["until"]:
            raise SourceFailure("rate_limited", 429)
        try:
            r = _lx_raw(url, timeout=30, **kw)
        except SourceFailure as error:
            if error.state == "rate_limited":
                _wb_state["until"] = time.time() + WB_BACKOFF
            if error.status == 503:
                if attempt == 0:
                    _lx_retry_pause()
                    continue
                raise SourceFailure("unavailable", 503) from None
            raise
        if r is not None and r.status_code == 429:
            _wb_state["until"] = time.time() + WB_BACKOFF
            _lx_tl.incomplete = True
            raise SourceFailure("rate_limited", 429)
        if r is not None and r.ok:
            return r
        if attempt == 0:
            _lx_retry_pause()
    raise SourceFailure("unavailable")


def _lx_wayback(host, title, deadline):
    pages: dict[str, tuple[int, str]] = {}
    for v in _lx_variants(title):
        if time.time() > deadline:
            break
        slug = v.replace(" ", "_")
        r = _wb(
            f"{WB}/cdx/search/cdx",
            params={
                "url": f"{host}/wiki/{slug}",
                "matchType": "prefix",
                "limit": 60,
                "fl": "original",
                "filter": "statuscode:200",
                "collapse": "urlkey",
            },
        )
        for line in r.text.splitlines() if r else []:
            name = (
                urllib.parse.unquote(line.strip().split("/wiki/", 1)[-1])
                .replace("_", " ")
                .split("?")[0]
                .split("#")[0]
            )
            rest = name[len(v) :].strip() if name.lower().startswith(v.lower()) else None
            if rest is None or (rest and not re.fullmatch(r"\(([^)]+)\)", rest)):
                continue  # "Title Of Something Else" / "Title/Sub"
            qual = rest[1:-1].lower() if rest else ""
            if qual and not any(q in qual for q in LX_PUB):
                continue  # "(Character)", "(Planet)" ...
            pages.setdefault(name, (0 if qual else 1, name))
        if pages:
            break
    out: list[tuple] = []
    for _, name in sorted(pages.values())[:3]:
        if time.time() > deadline:
            break
        url = f"https://{host}/wiki/" + urllib.parse.quote(name.replace(" ", "_"), safe="()_:,'!")
        try:
            r = _wb(f"{WB}/web/20300101000000id_/{url}")
            box = lx_infobox(r.text) if r else None
            urls = _lx_wb_images(urllib.parse.urljoin(f"https://{host}", box["img"])) if box else []
        except SourceFailure:
            if not out:
                raise
            _lx_tl.incomplete = True
            break
        if urls:
            out.append((name, box, urls))
    return out


def _lx_wb_images(full):
    """Archived copies of a wiki image: the original first, then the largest thumbnails.
    Asks CDX for real image captures, since some snapshots are Cloudflare challenge pages."""
    m = re.match(r"(https?://[^/]+/mediawiki/images)/(.+)$", full)
    if not m:
        return []
    caps: list[tuple] = []
    for url, prefix, orig in ((full, False, 1), (f"{m.group(1)}/thumb/{m.group(2)}/", True, 0)):
        params = {
            "url": url,
            "fl": "timestamp,original,length",
            "filter": ["statuscode:200", "mimetype:image/.*"],
            "limit": 200,
        }
        if prefix:
            params["matchType"] = "prefix"
        try:
            r = _wb(f"{WB}/cdx/search/cdx", params=params)
        except SourceFailure:
            if not caps:
                raise
            _lx_tl.incomplete = True
            break
        for line in r.text.splitlines() if r else []:
            f = line.split()
            if len(f) == 3 and f[0].isdigit() and f[2].isdigit():
                px = re.search(r"/(\d+)px-[^/]+$", f[1])
                caps.append((orig, int(px.group(1)) if px else 0, f[0], f[1]))
    best: dict[str, tuple] = {}
    for c in sorted(caps, reverse=True):  # per URL: the newest capture
        best.setdefault(c[3], c)
    ranked = sorted(best.values(), reverse=True)[:3]
    return [f"{WB}/web/{ts}id_/{u}" for _, _, ts, u in ranked]


def _lx_wiki_order(title):
    words = norm(title)
    hints = (
        (
            "ageofsigmar.lexicanum.com",
            ("age of sigmar", "stormcast", "mortal realms", "realm wars"),
        ),
        (
            "whfb.lexicanum.com",
            (
                "warhammer fantasy",
                "old world",
                "gotrek",
                "felix",
                "ulric",
                "malus darkblade",
                "end times",
            ),
        ),
    )
    first = next(
        (host for host, terms in hints if any(term in words for term in terms)), LX_WIKIS[0]
    )
    return [first] + [host for host in LX_WIKIS if host != first]


def src_lexicanum(title, author, isbn=None, budget=LX_DEADLINE):
    if not title:
        return []
    _lx_tl.incomplete = False
    key = (norm(title), norm(author))
    hit = _lx_cache.get(key)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    background = budget > LX_DEADLINE
    if background:
        _lx_bg.acquire()
    try:
        deadline = time.time() + budget
        out = _src_lexicanum(title, author, deadline)
    finally:
        _lx_tl.deadline = float("inf")
        if background:
            _lx_bg.release()
    if time.time() >= deadline:
        _lx_tl.incomplete = True
    if not _lx_tl.incomplete:
        if len(_lx_cache) >= 128:
            _lx_cache.pop(next(iter(_lx_cache)))
        _lx_cache[key] = (time.time(), out)
    return out


def _src_lexicanum(title, author, deadline):
    completed = 0
    hosts = _lx_wiki_order(title)
    for index, host in enumerate(hosts):
        remaining = deadline - time.time()
        if remaining <= 1:
            _lx_tl.incomplete = True
            break
        # The likely wiki gets most of the budget; reserve one small fallback slice.
        wiki_deadline = min(deadline, time.time() + remaining * (0.75 if index == 0 else 1))
        _lx_tl.deadline = wiki_deadline
        try:
            hits = _lx_wayback(host, title, wiki_deadline)
            if time.time() >= wiki_deadline:
                _lx_tl.incomplete = True
            else:
                completed += 1
        except SourceFailure as error:
            if not completed and error.state != "timed_out":
                raise
            _lx_tl.incomplete = True
            if error.state in {"rate_limited", "unavailable"}:
                break
            continue
        out = []
        for name, box, urls in hits:
            # a short printed only inside another book shows that book's cover, captioned with its name:
            # score it under the caption so it can't pose as the story's own cover
            bare = lambda n: re.sub(r"\s*\([^)]*\)$", "", n)
            other = [
                l
                for l in box["caption_links"]
                if similarity(bare(l), bare(name)) < 0.75 and similarity(bare(l), title) < 0.75
            ]
            shown = box["caption"] if other else bare(name)
            out.append(
                {
                    "src": "Lexicanum (archived copy)",
                    "title": shown,
                    "author": box["author"],
                    "urls": urls,
                    "timeout": 30,
                }
            )
        if out:
            return out
    return []


GR_ROW = re.compile(r'<tr itemscope itemtype="http://schema.org/Book">(.*?)</tr>', re.DOTALL)


def gr_full(u):
    """Cover thumbs carry a size suffix (…/625603._SY75_.jpg); without it you get the original upload."""
    return re.sub(r"\._[A-Z]{2}[0-9_,]+_\.(jpg|png)$", r".\1", u)


def gr_title(t):
    return re.sub(r"\s*\([^()]*#[\d.]+\)\s*$", "", html.unescape(t).strip())  # drop "(Series, #1)"


def gr_parse(page, url, by_isbn=False):
    """A Goodreads book page or search results page -> candidates. by_isbn: the search was an ISBN,
    so its top result is that edition (older layouts redirected to the book page instead)."""
    out = []
    m = (
        re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.DOTALL)
        if "/book/show/" in url
        else None
    )
    if m:
        try:
            d = json.loads(m.group(1))
        except ValueError:
            d = {}
        if d.get("image") and "nophoto" not in d["image"].lower():
            out.append(
                {
                    "src": "Goodreads",
                    "urls": [gr_full(d["image"])],
                    "title": gr_title(d.get("name", "")),
                    "by_isbn": by_isbn,
                    "isbn": english_isbn([d.get("isbn")]),
                    "author": ", ".join(a.get("name", "") for a in (d.get("author") or [])[:2]),
                }
            )
    # current (Next.js) search page: one <div class="Book"> card per result; its src is the full-size cover.
    # The page is streamed, so a card's title/authors may arrive later in the HTML than its cover:
    # join the two by book id instead of reading each card in order.
    details = {}
    for d in page.split('data-testid="book-item-title"')[1:]:
        m = re.match(r'><a href="/book/show/(\d+)[^"]*"[^>]*>([^<]+)<', d)
        if m:
            d = d.split('data-testid="book-item-title"')[0].split(
                'data-testid="book-item-content"'
            )[0]
            details[m.group(1)] = (
                gr_title(m.group(2)),
                [
                    html.unescape(x)
                    for x in re.findall(r'class="ContributorLink__name"[^>]*>([^<]+)<', d)[:2]
                ],
            )
    for card in page.split('<div class="Book" data-testid="book-item-')[1:7]:
        bid = re.search(r'href="/book/show/(\d+)', card)
        img = re.search(r'<img[^>]*class="ResponsiveImage"[^>]*\ssrc="([^"]+)"', card)
        if not (bid and img) or "nophoto" in img.group(1):
            continue
        alt = re.search(r'<img[^>]*\salt="([^"]*?)(?: Book Cover)?"', card)
        t, a = details.get(bid.group(1), (gr_title(alt.group(1)) if alt else "", []))
        out.append(
            {
                "src": "Goodreads",
                "urls": [gr_full(html.unescape(img.group(1)))],
                "title": t,
                "author": ", ".join(a),
                "by_isbn": by_isbn and not out,
            }
        )
    # older search page layout (table rows)
    for row in GR_ROW.findall(page)[:6]:
        img = re.search(r'class="bookCover"[^>]*src="([^"]+)"', row)
        t = re.search(r"itemprop='name'[^>]*>([^<]+)<", row)
        a = re.search(r'class="authorName"[^>]*><span itemprop="name">([^<]+)<', row)
        if img and "nophoto" not in img.group(1):
            out.append(
                {
                    "src": "Goodreads",
                    "urls": [gr_full(img.group(1))],
                    "title": gr_title(t.group(1)) if t else "",
                    "author": html.unescape(a.group(1)) if a else "",
                    "by_isbn": by_isbn and not out,
                }
            )
    return out
