"""Worker-side Goodreads cache and live wiki covers; no browser in application roles."""

import hashlib
import http.client
import json
import re
import socket
import threading
import time
from datetime import timedelta
from urllib.parse import quote, urlencode, urljoin, urlsplit
from xml.etree import ElementTree

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from librarium.cover_browser_parsing import parse_page
from librarium.cover_providers import similarity
from librarium.cover_source_protocol import WIKI_HOSTS, browser_signature, browser_url
from librarium.models import SourceBrowserPage

CACHE_ROWS = 128
CACHE_TTL = timedelta(hours=6)
MAX_PAGE = 2 * 1024 * 1024
BROWSER_LOCK = threading.Lock()
BROWSER_QUEUE_SECONDS = 90


def browser_call(path, value, maximum=6 * 1024 * 1024):
    if not settings.LIBRARIUM_SOURCE_BROWSER_ENABLED:
        return {"state": "unavailable"}
    secret = settings.LIBRARIUM_SOURCE_BROWSER_SECRET
    if len(secret) < 32 or not secret.isascii():
        return {"state": "unavailable"}
    # Chrome serializes commands; queueing must not consume the image fetch deadline.
    if not BROWSER_LOCK.acquire(timeout=BROWSER_QUEUE_SECONDS):
        return {"state": "busy"}
    try:
        return _browser_call(path, value, maximum, secret)
    finally:
        BROWSER_LOCK.release()


def _browser_call(path, value, maximum, secret):
    body, stamp = json.dumps(value).encode(), str(int(time.time()))
    seconds = 20 if path == "/image" else 85
    c = http.client.HTTPConnection("source-browser", 8126, timeout=seconds)
    sock = None

    def interrupt():
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        c.close()

    watchdog = threading.Timer(seconds, interrupt)
    watchdog.daemon = True
    watchdog.start()
    try:
        c.request(
            "POST",
            path,
            body,
            {
                "Content-Type": "application/json",
                "X-Source-Time": stamp,
                "X-Source-Signature": browser_signature(secret, path, body, stamp),
            },
        )
        sock = c.sock
        response = c.getresponse()
        if response.status == 503:
            return {"state": "busy"}
        if response.status != 200:
            return {"state": "unavailable"}
        length = response.getheader("Content-Length", "")
        if not length.isdecimal() or not 0 < int(length) <= maximum:
            raise ValueError
        raw = response.read(int(length) + 1)
        if len(raw) != int(length):
            raise ValueError
        if response.getheader("Content-Type") == "application/octet-stream" and path == "/image":
            return raw
        value = json.loads(raw)
        if type(value) is not dict or value.get("state") not in {
            "ok",
            "busy",
            "challenged",
            "unavailable",
            "timed_out",
            "rate_limited",
            "failed",
            "empty",
        }:
            raise ValueError
        return value
    except TimeoutError:
        return {"state": "timed_out"}
    except ValueError, OSError, http.client.HTTPException:
        return {"state": "unavailable"}
    finally:
        watchdog.cancel()
        c.close()


def challenge(page):
    return bool(
        re.search(
            r"<title>\s*(?:Just a moment|Access Denied)|challenge-platform|aws-waf-token|captcha",
            page,
            re.IGNORECASE,
        )
    )


def goodreads(query, *, retry=False):
    queries = [(query["isbn"], True)] if query["isbn"] else []
    if query["title"]:
        queries.append(((query["title"] + " " + query["author"]).strip(), False))
    for text, by_isbn in queries:
        key = hashlib.sha256(("goodreads-v1:" + text).encode()).hexdigest()
        cached = (
            None
            if retry
            else SourceBrowserPage.objects.filter(
                pk=key, checked_at__gt=timezone.now() - CACHE_TTL
            ).first()
        )
        if cached:
            page = {"html": cached.html, "url": cached.url, "state": "ok"}
        else:
            page = browser_call(
                "/goodreads",
                {"url": "https://www.goodreads.com/search?" + urlencode({"q": text})},
                3 * MAX_PAGE,
            )
        if page["state"] != "ok":
            return {"state": page["state"], "candidates": []}
        try:
            browser_url(page["url"], "goodreads")
            markup = page["html"]
            if type(markup) is not str or len(markup.encode()) > MAX_PAGE:
                raise ValueError
            if challenge(markup):
                return {"state": "challenged", "candidates": []}
            found = parse_page("goodreads", markup, page["url"], by_isbn)
            if not found and not any(
                marker in markup
                for marker in (
                    "no-book-search-results",
                    "book-item-content",
                    'itemtype="http://schema.org/Book"',
                )
            ):
                raise ValueError
        except ValueError, TypeError, KeyError, AttributeError:
            return {"state": "failed", "candidates": []}
        if not cached:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [63921842])
                SourceBrowserPage.objects.update_or_create(
                    pk=key,
                    defaults={"html": markup, "url": page["url"], "checked_at": timezone.now()},
                )
                SourceBrowserPage.objects.filter(
                    checked_at__lte=timezone.now() - CACHE_TTL
                ).delete()
                excess = list(
                    SourceBrowserPage.objects.order_by("-checked_at", "query_key").values_list(
                        "query_key", flat=True
                    )[CACHE_ROWS:]
                )
                SourceBrowserPage.objects.filter(pk__in=excess).delete()
        if found:
            for item in found:
                item["reach_method"] = "server_browser"
            return {"state": "results", "candidates": found[:6]}
    return {"state": "empty", "candidates": []}


def lexicanum(query):
    if not query["title"]:
        return {"state": "empty", "candidates": []}
    title = quote(query["title"].replace(" ", "_"), safe="()_,-!")
    deadline = time.monotonic() + 80
    for host in WIKI_HOSTS:
        if time.monotonic() >= deadline:
            return {"state": "timed_out", "candidates": []}
        page = browser_call("/lexicanum", {"url": f"https://{host}/wiki/{title}"}, 6 * MAX_PAGE)
        if page["state"] == "empty":
            search_url = f"https://{host}/mediawiki/index.php?" + urlencode(
                {
                    "title": "Special:Search",
                    "search": (query["title"] + " " + query["author"]).strip(),
                    "fulltext": "1",
                    "limit": "5",
                    "ns0": "1",
                }
            )
            if time.monotonic() >= deadline:
                return {"state": "timed_out", "candidates": []}
            search = browser_call("/lexicanum_search", {"url": search_url}, 6 * MAX_PAGE)
            if search["state"] != "ok":
                if search["state"] == "empty":
                    continue
                return {"state": search["state"], "candidates": []}
            try:
                browser_url(search["url"], "lexicanum_search")
                if urlsplit(search["url"]).hostname != host:
                    raise ValueError
                matches = parse_page("lexicanum_search", search["html"], search["url"])
                matches = sorted(
                    (
                        m
                        for m in matches
                        if re.search(
                            r"\b(?:books?|novels?|novellas?|short[\s_]+stor(?:y|ies)|audio[\s_]+(?:dramas?|books?))\b",
                            m["title"]
                            + " "
                            + m["url"].rsplit("/", 1)[-1].replace("_", " ")
                            + " "
                            + m["snippet"],
                            re.IGNORECASE,
                        )
                    ),
                    key=lambda m: (
                        -similarity(query["title"], re.sub(r"\s*\([^)]*\)$", "", m["title"])),
                        -similarity(query["author"], m["snippet"]),
                        m["url"],
                    ),
                )
                page = {"state": "empty"}
                for match in matches[:2]:
                    if (
                        similarity(query["title"], re.sub(r"\s*\([^)]*\)$", "", match["title"]))
                        < 0.7
                    ):
                        continue
                    browser_url(match["url"], "lexicanum")
                    if urlsplit(match["url"]).hostname != host:
                        raise ValueError
                    if time.monotonic() >= deadline:
                        return {"state": "timed_out", "candidates": []}
                    page = browser_call("/lexicanum", {"url": match["url"]}, 6 * MAX_PAGE)
                    if page["state"] != "empty":
                        break
                if page["state"] == "empty":
                    continue
            except ValueError, TypeError, KeyError:
                return {"state": "failed", "candidates": []}
        if page["state"] != "ok":
            return {"state": page["state"], "candidates": []}
        try:
            browser_url(page["url"], "lexicanum")
            parsed = parse_page("lexicanum", page["html"], page["url"], xml=page["xml"])
            name, box = parsed["name"], parsed["box"]
            if not box:
                continue
            image = urljoin(page["url"], box["img"])
            browser_url(image, "image")
            if urlsplit(image).hostname != host:
                raise ValueError
            bare = re.sub(r"\s*\([^)]*\)$", "", name)
            other = [
                s
                for s in box["caption_links"]
                if similarity(s, bare) < 0.75 and similarity(s, query["title"]) < 0.75
            ]
            return {
                "state": "results",
                "candidates": [
                    {
                        "src": "Lexicanum (live)",
                        "title": box["caption"] if other else bare,
                        "author": box["author"],
                        "urls": [image],
                        "reach_method": "server_browser",
                    }
                ],
            }
        except ValueError, TypeError, KeyError, ElementTree.ParseError:
            return {"state": "failed", "candidates": []}
    return {"state": "empty", "candidates": []}
