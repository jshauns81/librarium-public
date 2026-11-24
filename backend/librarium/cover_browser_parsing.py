"""Bounded fresh parsing of browser HTML; no application configuration or credentials."""

import json
import os
import subprocess
import sys
from pathlib import Path

MAX_PAGE = 2 * 1024 * 1024


def wiki_search(page, url):
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlsplit

    from librarium.cover_source_protocol import browser_url

    if not any(marker in page for marker in ("mw-search-results", "mw-search-nonefound")):
        raise ValueError("Unrecognised wiki search response.")

    class SearchParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.rows = []
            self.current = None
            self.heading = False
            self.link = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "li":
                self.current = {"title": "", "snippet": "", "url": ""}
            if "mw-search-result-heading" in attrs.get("class", "").split():
                self.heading = True
            if tag == "a" and self.heading and self.current is not None:
                self.link = urljoin(url, attrs.get("href", ""))
                self.current["url"] = self.link

        def handle_endtag(self, tag):
            if tag == "a":
                self.link = None
            if tag == "div":
                self.heading = False
            if tag == "li" and self.current is not None:
                item = self.current
                self.current = None
                try:
                    browser_url(item["url"], "lexicanum")
                    if urlsplit(item["url"]).hostname != urlsplit(url).hostname:
                        return
                    if item["title"] and len(self.rows) < 5:
                        self.rows.append({k: " ".join(v.split()) for k, v in item.items()})
                except ValueError:
                    pass

        def handle_data(self, data):
            if self.current is not None:
                self.current["snippet"] = (self.current["snippet"] + " " + data)[:2048]
                if self.link:
                    self.current["title"] = (self.current["title"] + data)[:512]

    parser = SearchParser()
    parser.feed(page)
    return parser.rows


def parse_page(kind, page, url, by_isbn=False, *, xml=None):
    if (
        type(page) is not str
        or len(page.encode()) > MAX_PAGE
        or (xml is not None and (type(xml) is not str or len(xml.encode()) > MAX_PAGE))
    ):
        raise ValueError("Browser page is too large.")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "librarium.cover_browser_parsing"],
            input=json.dumps(
                {"kind": kind, "page": page, "url": url, "by_isbn": by_isbn, "xml": xml}
            ).encode(),
            cwd=Path(__file__).resolve().parents[1],
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=8,
        )
        if len(result.stdout) > 128 * 1024:
            raise ValueError
        return json.loads(result.stdout)
    except ValueError, OSError, subprocess.SubprocessError:
        raise ValueError("The browser page could not be parsed within its limits.") from None


def main():
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    from urllib.parse import unquote, urlsplit
    from xml.etree import ElementTree

    from librarium.cover_providers import gr_parse, lx_infobox
    from librarium.xml_policy import guard

    value = json.loads(sys.stdin.buffer.read(12 * MAX_PAGE + 16384))
    if value["kind"] == "goodreads":
        result = gr_parse(value["page"], value["url"], value["by_isbn"])
    elif value["kind"] == "lexicanum_search":
        result = wiki_search(value["page"], value["url"])
    elif value["kind"] == "lexicanum":
        guard(value["xml"].encode())
        root = ElementTree.fromstring(value["xml"])
        ns = "{http://www.mediawiki.org/xml/export-0.10/}"
        pages = root.findall(ns + "page")
        if (
            root.tag != ns + "mediawiki"
            or len(pages) != 1
            or len(pages[0].findall(ns + "revision")) != 1
        ):
            raise ValueError
        name = pages[0].findtext(ns + "title", "")
        if name.replace(" ", "_") != unquote(urlsplit(value["url"]).path[6:]):
            raise ValueError
        result = {"name": name, "box": lx_infobox(value["page"])}
    else:
        raise ValueError
    raw = json.dumps(result, allow_nan=False).encode()
    if len(raw) > 128 * 1024:
        raise ValueError
    sys.stdout.buffer.write(raw)


if __name__ == "__main__":
    try:
        main()
    except ValueError, KeyError, TypeError, AttributeError:
        os._exit(2)
