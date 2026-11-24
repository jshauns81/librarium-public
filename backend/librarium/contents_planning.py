"""Read-only contents proposals from bounded source observations, not EPUB repair.

Policy v2 ports Library Finish's lab-settled "Make Kindle-ready" contents rebuild (KC,
KCa and KCb; D086-D088) from LF 72bdf39 bin/epub_content.py:567-1036 (candidates,
gap filling, stubs, levels, nesting, omnibus books) and 1110-1310 (keep, rebuild or
refuse). LF parses each page itself; here every rule reads inspection v10 observations:
headings, short title-like paragraph lines, anchors, links and per-page counts.

Differences kept on purpose: a rebuild whose list equals the book's own list is a
keep, because it would change nothing; LF's library-wide author names and its removal
of store pages before planning are not available; kept lists are never pruned. Each
proposed entry keeps an exact source position and label source, a missing anchor stays
``requires_anchor``, and nothing here changes source bytes, navigation or the library.
"""

import bisect
import collections
import re

from librarium import contents_rules as rules

POLICY_VERSION = "librarium.contents-plan.v2"
HISTORICAL_POLICY_VERSION = "librarium.contents-plan.v1"
INSPECTION_POLICY = "librarium.epub-structure.v10"
MAX_ENTRIES = 2048
MAX_DEPTH = 8
MAX_PROBLEMS = 3
LIMITATIONS = [
    (
        "Read-only: no source bytes, navigation or library records changed; EPUBCheck, "
        "story completeness and readiness were not checked."
    ),
    "Library Finish's contents rules on recorded headings, short lines, anchors and links.",
    "At most 2048 recorded and proposed entries and eight levels.",
]
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_NAVIGATION_ERRORS = {"missing_navigation", "empty_navigation"}


class _Held(Exception):
    pass


def held_plan(report, reason):
    return {
        "policy_version": POLICY_VERSION,
        "source_sha256": report.get("source_sha256"),
        "inspection_policy": report.get("policy", {}).get("version"),
        "decision": "held",
        "reason_codes": [reason],
        "existing": [],
        "entries": [],
        "excluded_targets": [],
        "limitations": list(LIMITATIONS),
        "measures": None,
        "problems": [],
        "ready": False,
    }


MEASURES = ("existing", "headings", "linked", "entries", "words")


def valid_findings(plan):
    """A v2 plan's measures are None or five counts, and it has at most three findings."""
    measures, problems = plan.get("measures", ...), plan.get("problems")
    return (
        (
            measures is None
            or isinstance(measures, dict)
            and set(measures) == set(MEASURES)
            and all(_integer(measures[name]) for name in MEASURES)
        )
        and isinstance(problems, list)
        and len(problems) <= MAX_PROBLEMS
        and all(isinstance(problem, str) for problem in problems)
    )


def _integer(value):
    return type(value) is int and value >= 0


def _fold(label):
    return " ".join(label.casefold().split())


def _demoted(heading):
    """A heading LF would demote: prose, not a link, not a chapter number run into a sentence."""
    text = heading["label"]
    return (
        rules.prose(text)
        and not heading.get("only_link", False)
        and not any(rules.number_key(" ".join(text.split()[:k])) for k in (1, 2, 3))
    )


class _Doc:
    def __init__(self, item, index, story_index):
        self.item = item
        self.path = item["path"]
        self.index = index
        self.story_index = story_index
        self.sha = item["byte_sha256"]
        self.words = item["body_word_count"] or 0
        self.media = item["media_count"] or 0
        self.signals = item.get("contents_signals") or {}
        self.anchors = {anchor["id"]: anchor for anchor in item["anchors"]}
        self._starts = sorted(item["anchors"], key=lambda anchor: anchor["source_index"])
        # LF plans after Make Kindle-ready turns prose tagged as a heading back into a paragraph
        # (kindle_fixes, LF 72bdf39 bin/epub_content.py:1550-1566); the markup here is unchanged.
        self.headings = [
            self._observed(h, only_link=h.get("only_link", False))
            for h in item["headings"]
            if h["label"].strip() and not _demoted(h)
        ]
        # Each demoted heading becomes a paragraph in LF, so lines after it move down one place.
        demoted = sorted(
            h["source_index"] for h in item["headings"] if h["label"].strip() and _demoted(h)
        )
        blocks = [
            self._observed(
                b,
                inline=b.get("inline", False),
                ordinal=None
                if b["ordinal"] is None
                else b["ordinal"] + bisect.bisect_left(demoted, b["source_index"]),
            )
            for b in item.get("blocks", [])
        ]
        self.blocks = [b for b in blocks if not b["inline"]]
        self.inline = [b for b in blocks if b["inline"]]
        self.internal = sum(
            1
            for link in item["links"]
            if link.get("tag") == "a"
            and link.get("attribute") == "href"
            and not link.get("external")
            and link.get("target_path") != self.path
        )

    def _observed(self, source, **extra):
        """A heading or line with LF's id: its own, else an anchor directly at its start."""
        ident = source.get("id") or None
        own = bool(ident) or bool(source.get("has_id"))
        if not ident:
            ident = self._loose_anchor(source)
        return {
            **source,
            **extra,
            "id": ident,
            "has_id": own,
            "class": source.get("class", ""),
        }

    def _loose_anchor(self, source):
        """An anchor with no words or media between it and ``source`` (LF loose_id)."""
        fields = ("word_offset", "non_heading_word_offset", "media_offset")
        same = [
            anchor
            for anchor in self._starts
            if all(anchor[field] == source[field] for field in fields)
        ]
        before = [a for a in same if a["source_index"] < source["source_index"]]
        inside = [a for a in same if a["source_index"] > source["source_index"]]
        chosen = before[-1] if before else inside[0] if inside else None
        return chosen["id"] if chosen else None

    def printed_contents(self):
        """A printed contents page: mostly links into the book, or headed Contents."""
        return (self.internal >= 3 and self.words <= 12 * self.internal) or bool(
            self.headings and rules.CONTENTS_HEADING.match(self.headings[0]["label"])
        )


class _Evidence:
    def __init__(self, report):
        if report.get("inspection_complete") is not True or report.get("findings_truncated"):
            raise _Held("inspection_incomplete")
        if report.get("policy", {}).get("version") != INSPECTION_POLICY:
            raise _Held("source_evidence_unavailable")
        if (
            not _DIGEST.fullmatch(report.get("source_sha256") or "")
            or report.get("expected_sha256") != report["source_sha256"]
        ):
            raise _Held("source_evidence_unavailable")
        errors = [f["code"] for f in report.get("findings", []) if f.get("severity") == "error"]
        if any(code not in _NAVIGATION_ERRORS for code in errors):
            raise _Held("structural_failure")
        self.navigation_errors = {
            f["code"] for f in report.get("findings", []) if f["code"] in _NAVIGATION_ERRORS
        }
        if report.get("contents_observations", {}).get("status") != "recorded":
            raise _Held("contents_evidence_unavailable")
        documents = {doc["path"]: doc for doc in report["documents"]}
        if len(documents) != len(report["documents"]):
            raise _Held("source_evidence_unavailable")
        navigation = report["navigation"]
        self.nav_paths = set(navigation["nav_paths"]) | set(navigation["ncx_paths"])
        media = {item["path"]: item["media_type"] for item in report["manifest"]}
        self.story: list[_Doc] = []
        self.spine_paths = []
        seen = set()
        for item in report["spine"]:
            path = item["path"]
            if path in seen:
                raise _Held("target_order")
            seen.add(path)
            self.spine_paths.append(path)
            if path in self.nav_paths:
                continue
            doc = documents.get(path)
            if doc is None or not _DIGEST.fullmatch(doc.get("byte_sha256") or ""):
                raise _Held("source_evidence_unavailable")
            if media.get(path) == "image/svg+xml" and doc.get("body_word_count") is None:
                doc = {**doc, "headings": [], "anchors": doc["anchors"], "links": doc["links"]}
            elif not all(
                _integer(doc.get(field))
                for field in ("body_word_count", "non_heading_word_count", "media_count")
            ):
                raise _Held("source_evidence_unavailable")
            self._validate(doc)
            self.story.append(_Doc(doc, len(self.story), len(self.story)))
        if not self.story:
            raise _Held("unsupported_structure")
        self.by_path = {doc.path: doc for doc in self.story}
        self.documents = documents
        self.creators = rules.creators(
            entry["text"] for entry in report["metadata"] if entry["name"] == "creator"
        )
        self.title = next(
            (" ".join(e["text"].split()) for e in report["metadata"] if e["name"] == "title"), ""
        )
        self.package = report["package"]
        self.epub3 = str(self.package["version"]).startswith("3")
        self.words = sum(doc.words for doc in self.story)
        self.scan = any(
            documents.get(path, {}).get("contents_signals", {}).get("ocr_scan")
            for path in self.spine_paths[:4]
        )

    @staticmethod
    def _position_valid(source, doc):
        return all(
            _integer(source.get(field))
            for field in ("source_index", "word_offset", "non_heading_word_offset", "media_offset")
        ) and all(
            source[field] <= (doc[total] or 0)
            for field, total in (
                ("word_offset", "body_word_count"),
                ("non_heading_word_offset", "non_heading_word_count"),
                ("media_offset", "media_count"),
            )
        )

    def _validate(self, doc):
        previous = -1
        for source in [*doc["headings"], *doc.get("blocks", [])]:
            if (
                not self._position_valid(source, doc)
                or not isinstance(source.get("label"), str)
                or not isinstance(source.get("has_id", False), bool)
                or not isinstance(source.get("class", ""), str)
            ):
                raise _Held("source_evidence_unavailable")
        for block in doc.get("blocks", []):
            if block["ordinal"] is not None and not _integer(block["ordinal"]):
                raise _Held("source_evidence_unavailable")
        for heading in doc["headings"]:
            if (
                type(heading.get("level")) is not int
                or not 1 <= heading["level"] <= 6
                or not isinstance(heading.get("only_link", False), bool)
                or heading["source_index"] <= previous
            ):
                raise _Held("source_evidence_unavailable")
            previous = heading["source_index"]
        ids = set()
        for anchor in doc["anchors"]:
            if not self._position_valid(anchor, doc) or not anchor.get("id"):
                raise _Held("source_evidence_unavailable")
            if anchor["id"] in ids:
                raise _Held("duplicate_target")
            ids.add(anchor["id"])

    def resolve(self, path, fragment):
        """(doc, position) for a link target; the position is the anchor or the document start."""
        doc = self.by_path.get(path)
        if doc is None:
            return None, None
        if fragment:
            anchor = doc.anchors.get(fragment)
            return (doc, anchor) if anchor is not None else (doc, None)
        return doc, {"source_index": 0, "word_offset": 0, "non_heading_word_offset": 0}


# Candidates are LF's dicts: path, fragment, label, level, linkable, native, alone, opens,
# pos (source index), styled and anchor, plus the observation each one came from.


def _item(source, kind, doc, **extra):
    return {
        "text": source["label"],
        "level": source.get("level"),
        "id": source.get("id"),
        "words_before": source["word_offset"],
        "pos": source["source_index"],
        "id_attr": source["has_id"],
        "class": source.get("class", ""),
        "ordinal": source.get("ordinal"),
        "kind": kind,
        "source": source,
        "doc": doc,
        **extra,
    }


def _front_pages(ev):
    """Front matter up to the last store or advert page, and pages before a printed contents."""
    front: list[str] = []
    last = -1
    for doc in ev.story:
        if len(front) >= rules.FRONT_SCAN or doc.words > rules.FRONT_SHORT:
            break
        if any(
            rules.STYLED_HEADING.match(h["label"]) or rules.chapter_number(h["label"]) is not None
            for h in doc.headings
            if not h["only_link"]
        ):
            break
        front.append(doc.path)
        if doc.signals.get("front_junk"):
            last = len(front) - 1
        if doc.printed_contents():
            last = max(last, len(front) - 2)
    return set(front[: last + 1])


def _first_line_styles(ev):
    """Paragraph classes that open three or more long pages without headings with a title."""
    counts: collections.Counter = collections.Counter()
    for doc in ev.story:
        if doc.words < 200 or doc.headings or doc.signals.get("first_line_link"):
            continue
        first = next((b for b in doc.blocks if b["ordinal"] == 0), None)
        if first and first["class"] and rules.title_line(rules.plain_label(first["label"])):
            counts[first["class"]] += 1
    return {name for name, count in counts.items() if count >= 3}


def _stub_headings(ev):
    """Chapter headings out of reading order: the end of a printed contents list made headings."""
    heads = []
    started = False
    for doc in ev.story:
        front = not started
        started = started or doc.words > rules.FRONT_SHORT
        if doc.internal >= 3 and doc.words <= 12 * doc.internal:
            continue
        entries = doc.headings
        for j, heading in enumerate(entries):
            label = heading["label"]
            found = rules.number_key(label)
            if (
                not found
                or found[0][0] != "chapter"
                or not (rules.chapter_number(label) is not None or ":" in label)
            ):
                continue
            end = entries[j + 1]["word_offset"] if j + 1 < len(entries) else doc.words
            after = end - heading["word_offset"] - len(label.split())
            if after >= rules.STUB_TEXT or not front:
                heads.append({"n": found[1], "style": found[0], "text": label, "real": True})
                continue
            heads.append(
                {
                    "path": doc.path,
                    "pos": heading["source_index"],
                    "text": label,
                    "n": found[1],
                    "style": found[0],
                }
            )
    runs: list[list[dict]] = []
    last: dict = {}
    for head in heads:
        style = head["style"]
        if style not in last or head["n"] in (0, 1) or head["n"] <= last[style][-1]["n"]:
            last[style] = []
            runs.append(last[style])
        last[style].append(head)
    out = set()
    for k, run in enumerate(runs):
        if run[0]["n"] in (0, 1) or any(h.get("real") for h in run):
            continue
        later = {rules.heading_key(h["text"]) for r in runs[k + 1 :] for h in r}
        if all(rules.heading_key(h["text"]) in later for h in run):
            out |= {(h["path"], h["pos"]) for h in run}
    return out


def _bylines(found, doc, creators, page_above):
    """found without story bylines tagged as headings; a title just above one takes its place."""
    out: list[dict] = []
    blocks = doc.blocks

    def right_above(head):
        at = head["words_before"]

        def gap(x):
            return at - x["words_before"] - len(x["text"].split())

        if out and 0 <= gap(out[-1]) <= 2:
            return out[-1], True
        if not out and at <= 2 and page_above:
            return {"text": page_above}, True
        block = next(
            (
                b
                for b in reversed(blocks)
                if b["word_offset"] < at
                and 0 <= at - b["word_offset"] - len(b["label"].split()) <= 2
            ),
            None,
        )
        if block and len(block["label"].split()) <= 8:
            return _item(block, "paragraph", doc), False
        return None, False

    for head in found:
        text = head["text"]
        shaped = bool(rules.BYLINE.match(text))
        above, heading = right_above(head)
        under_title = (
            shaped
            and above is not None
            and not rules.chapterish(above["text"])
            and not rules.BYLINE.match(above["text"])
        )
        edited = bool(re.match(r"(?i)edited\s+by\s", text)) and shaped
        if not (rules.author_line(text, creators) or under_title or edited):
            out.append(head)
            continue
        if above is not None and not heading and not rules.chapterish(above["text"]):
            out.append({**above, "level": head["level"]})
    return out


def _titled_story(blocks, k, doc):
    """blocks[k] is a story title: a title line, then a "by Author" line, then story text."""
    if k + 1 >= len(blocks):
        return False
    title, byline = blocks[k], blocks[k + 1]
    if (
        not rules.title_line(title["text"])
        or byline["ordinal"] != title["ordinal"] + 1
        or not rules.BY_LINE.match(byline["text"])
    ):
        return False
    if any(
        rules.heading_key(b["text"]) == rules.heading_key(title["text"]) for b in blocks[k + 2 :]
    ):
        return False
    following = next((b for b in blocks[k + 2 :] if rules.BY_LINE.match(b["text"])), None)
    end = following["words_before"] if following else doc.words
    return end - byline["words_before"] - len(byline["text"].split()) >= 50


def _listed_titles(blocks, after):
    """An unlinked printed contents list under a CONTENTS heading, found again as titles."""
    listed: list[str] = []
    k = 0
    while k < len(blocks) and blocks[k]["words_before"] < after:
        k += 1
    previous = None
    while (
        k < len(blocks)
        and len(blocks[k]["text"].split()) <= 12
        and rules.heading_key(blocks[k]["text"]) not in listed
        and (previous is None or blocks[k]["ordinal"] == previous + 1)
    ):
        if not rules.BY_LINE.match(blocks[k]["text"]):
            listed.append(rules.heading_key(blocks[k]["text"]))
        previous = blocks[k]["ordinal"]
        k += 1
    out: list[dict] = []
    for title in listed:
        hit = next(
            (
                b
                for b in blocks[k:]
                if rules.heading_key(b["text"]) == title and (not out or b["pos"] > out[-1]["pos"])
            ),
            None,
        )
        if hit:
            out.append({**hit, "level": 1, "styled": True})
    return out if len(out) >= 2 else []


def _styled(doc, title_styles):
    """Short styled paragraphs that open chapters, in a document without usable headings."""
    blocks = [_item(b, "paragraph", doc, text=rules.plain_label(b["label"])) for b in doc.blocks]
    found = []
    for k, block in enumerate(blocks):
        text, name, first = block["text"], block["class"], block["ordinal"] == 0
        if len(text) <= 100 and (
            rules.STYLED_HEADING.match(text)
            or (
                rules.CHAPTER_NUMBER.match(text)
                and (re.search("chapter", name, re.IGNORECASE) or (first and doc.words >= 200))
            )
            or (
                first
                and doc.words >= 200
                and rules.NUMBERED_TITLE.match(text)
                and not rules.prose(text)
            )
            or (
                first
                and doc.words >= 200
                and len(text) <= 60
                and re.search(r"chapter|title|heading", name, re.IGNORECASE)
                and not rules.prose(text)
            )
            or (first and doc.words >= 200 and name in title_styles and rules.title_line(text))
            or _titled_story(blocks, k, doc)
        ):
            found.append({**block, "level": 1, "styled": True})
    return blocks, found


def _heading_candidates(ev):
    """Chapter headings in reading order as the book prints them (LF _heading_candidates)."""
    out: list[dict] = []
    seen = set()
    junk = _front_pages(ev)
    creators = ev.creators
    page_above = None
    title_styles = _first_line_styles(ev)
    stubs = _stub_headings(ev)
    for doc in ev.story:
        if doc.path in junk:
            continue
        found = [_item(h, "heading", doc, only_link=h["only_link"]) for h in doc.headings]
        words = doc.words
        here, page_above = page_above, None
        if doc.internal >= 3 and words <= 12 * doc.internal:
            continue
        chapterlike = any(
            rules.STYLED_HEADING.match(h["text"]) or rules.chapter_number(h["text"]) is not None
            for h in found
            if not h["only_link"] and len(h["text"]) > 1
        )
        signals = doc.signals
        if not chapterlike and words <= 600 and signals.get("publisher_marks", 0) >= 2:
            continue
        if signals.get("front_junk_lead"):
            continue
        if not chapterlike and signals.get("backlist_links"):
            continue  # a backlist: store-link titles
        if not chapterlike and words <= 1500 and signals.get("backlist_bylines"):
            continue  # a backlist: titles and author lines
        linked = any(h["only_link"] for h in found)
        found = [
            h
            for h in found
            if not rules.DEBRIS_LABEL.match(h["text"])
            and not h["only_link"]
            and (doc.path, h["pos"]) not in stubs
        ]
        if len(found) >= 5 and words <= 15 * len(found):
            continue
        if sum(1 for h in found if rules.SERIES_ITEM.match(h["text"])) >= 3:
            continue
        letters = [
            h["text"]
            for h in found
            if re.fullmatch(r"[A-Z]\w{0,3}", h["text"]) and len(h["text"]) <= 4
        ]
        if not chapterlike and any(
            re.fullmatch(r"[A-Z]", x) and not re.fullmatch(rules.ROMAN, x) for x in letters
        ):
            continue
        if (
            found
            and rules.NOT_A_CHAPTER.match(found[0]["text"])
            and not rules.CONTENTS_HEADING.match(found[0]["text"])
        ):
            continue
        contents_at = None
        if found and rules.CONTENTS_HEADING.match(found[0]["text"]):
            contents_at = found[0]["words_before"]
            lead = found[0]["level"]
            rest = found[1:]
            k = 0
            while k < len(rest) and rest[k]["level"] > lead:
                k += 1
            found = rest[k:]
        found = _bylines(found, doc, creators, here)
        heads = doc.headings
        page_above = (
            heads[0]["label"]
            if len(heads) == 1 and words <= len(heads[0]["label"].split()) + 2
            else None
        )
        if not found and not linked:
            blocks, found = _styled(doc, title_styles)
            if contents_at is not None:
                found = _listed_titles(blocks, contents_at) or found
            if sum(1 for h in found if rules.SERIES_ITEM.match(h["text"])) >= 3:
                continue
            found = [h for h in found if not rules.author_line(h["text"], creators)]
        placed = False
        for head in found:
            label = rules.undoubled(rules.plain_label(head["text"]))
            key = (doc.path, head["id"] or label.lower())
            if rules.running_header(label, creators):
                continue
            if (
                rules.NOT_A_CHAPTER.match(label)
                or rules.HEADING_JUNK.match(label)
                or rules.prose(label)
                or key in seen
            ):
                continue
            if re.fullmatch(r"[ivxlcdm]+", label):
                continue
            seen.add(key)
            joined = None
            if (
                rules.BARE_DIVISION.match(label) or re.fullmatch(rules.ROMAN, label)
            ) and words <= 40:
                after = head["words_before"] + len(label.split())
                title = next((b for b in doc.blocks if b["word_offset"] >= after), None)
                # Only the very next line titles a part; an unrecorded line may lie between.
                text = title["label"] if title and title["word_offset"] == after else ""
                if (
                    text
                    and len(text.split()) <= 6
                    and text[-1:] not in ".!?,;"
                    and not rules.STYLED_HEADING.match(text)
                    and not rules.CHAPTER_NUMBER.match(text)
                ):
                    label = label + ": " + text
                    joined = title
            linkable = bool(head["id"]) or (
                not placed and head["words_before"] <= rules.OPENING_WORDS
            )
            candidate = {
                "path": doc.path,
                "fragment": head["id"],
                "label": label,
                "level": head["level"],
                "linkable": linkable,
                "native": linkable,
                "alone": words <= len(head["text"].split()) + 2,
                "opens": head["words_before"] <= 2,
                "pos": head["pos"],
                "styled": head.get("styled", False),
                "anchor": False,
                "item": head,
                "joined": joined,
            }
            if not linkable and not head["id_attr"]:
                candidate.update(linkable=True, anchor=True)
            placed = placed or candidate["linkable"]
            out.append(candidate)
    return out


def _fill_chapter_gaps(ev, cands):
    """A chapter number left as a plain paragraph fills a gap in the book's own numbering."""
    order = {doc.path: doc.index for doc in ev.story}
    # (number key, missing numbers, candidate before the gap, candidate after it)
    gaps: list[tuple[tuple, list[int], int | None, int | None]] = []
    prev: dict = {}
    counts: collections.Counter = collections.Counter()
    for i, c in enumerate(cands):
        found = rules.number_key(c["label"]) if c["path"] in order else None
        if not found:
            continue
        key, n = found
        counts[key] += 1
        p = prev.get(key)
        low = 1 if p is None or n <= p[1] else p[1] + 1
        if 0 < n - low <= rules.GAP:
            gaps.append((key, list(range(low, n)), None if p is None else p[0], i))
        prev[key] = (i, n)
    gaps = [g for g in gaps if counts[g[0]] >= 2]
    for i, c in enumerate(cands):
        found = rules.number_key(c["label"]) if c["path"] in order else None
        if not found:
            continue
        nxt = next(
            (
                j
                for j in range(i + 1, len(cands))
                if rules.number_key(cands[j]["label"])
                and rules.number_key(cands[j]["label"])[0] == found[0]
            ),
            None,
        )
        if nxt is not None and rules.number_key(cands[nxt]["label"])[1] > found[1]:
            continue
        stop = next((j for j in range(i + 1, len(cands)) if cands[j]["level"] <= c["level"]), None)
        gaps.append((found[0], list(range(found[1] + 1, found[1] + 200)), i, stop))
    taken = {(c["path"], c["pos"]) for c in cands}
    used: dict = collections.defaultdict(set)
    for c in cands:
        used[c["path"]].add(c["fragment"])
    parsed: dict = {}

    def items(doc):
        if doc.path not in parsed:
            found = [_item(h, "heading", doc) for h in doc.headings if not h["only_link"]] + [
                _item(b, "paragraph", doc) for b in doc.blocks
            ]
            found += [
                _item(b, "inline", doc, words_before=10**6, id=None, **{"class": "inline"})
                for b in doc.inline
            ]
            parsed[doc.path] = sorted(found, key=lambda x: x["pos"])
        return parsed[doc.path]

    added = []
    for key, missing, a, b in gaps:
        start = (order[cands[a]["path"]], cands[a]["pos"]) if a is not None else (0, -1)
        ahead = b is None or len(missing) > rules.GAP
        side = cands[a] if ahead else cands[b]
        end = (order[cands[b]["path"]], cands[b]["pos"]) if b is not None else (len(ev.story), 0)
        prefixed = bool(re.match(r"(?i)chapter\b", side["label"]))
        want = list(missing)
        found_here = []
        for doc in ev.story[start[0] : end[0] + 1]:
            for it in items(doc):
                at = (doc.index, it["pos"])
                if not want or at <= start or at >= end or (doc.path, it["pos"]) in taken:
                    continue
                text = " ".join(it["text"].split())
                found = rules.number_key(text) if len(text) <= 100 else None
                if found != (key, want[0]) and it["kind"] == "heading":
                    head = next(
                        (
                            " ".join(text.split()[:k])
                            for k in (1, 2, 3)
                            if rules.number_key(" ".join(text.split()[:k])) == (key, want[0])
                        ),
                        None,
                    )
                    if head:
                        found, text = (key, want[0]), head
                if (
                    found == (key, want[0])
                    and bool(re.match(r"(?i)chapter\b", text)) == prefixed
                    and not rules.prose(text)
                ):
                    candidate = {
                        "path": doc.path,
                        "fragment": it["id"],
                        "label": text,
                        "level": side["level"],
                        "linkable": bool(it["id"]),
                        "native": bool(it["id"]),
                        "pos": it["pos"],
                        "alone": False,
                        "opens": it["words_before"] <= 2,
                        "styled": False,
                        "anchor": False,
                        "item": it,
                        "joined": None,
                        "_class": it["class"] if it["kind"] != "heading" else "h",
                    }
                    if (
                        not it["id"]
                        and it["words_before"] <= rules.OPENING_WORDS
                        and not any(c["path"] == doc.path and c["pos"] < it["pos"] for c in cands)
                    ):
                        candidate.update(linkable=True, native=True)
                    elif not it["id"] and not it["id_attr"]:
                        candidate.update(linkable=True, anchor=True)
                    found_here.append(candidate)
                    taken.add((doc.path, it["pos"]))
                    want.pop(0)
        if ahead and (len(found_here) < 2 or len({c["_class"] for c in found_here}) > 1):
            for c in found_here:
                taken.discard((c["path"], c["pos"]))
            found_here = []
        added += [{k: v for k, v in c.items() if k != "_class"} for c in found_here]
    cands = sorted(cands + added, key=lambda c: (order.get(c["path"], -1), c["pos"]))
    levels = collections.Counter(
        c["level"]
        for c in cands
        if not c["styled"] and rules.chapter_number(c["label"]) is not None
    )
    if levels:
        # most_common() would import heapq inside the sandbox; max keeps its first-seen tie.
        level = max(levels, key=levels.__getitem__)
        cands = [
            {**c, "level": level}
            if c["styled"] and rules.chapter_number(c["label"]) is not None
            else c
            for c in cands
        ]
    return cands


def _drop_stray_numbers(cands):
    """Page numbers made headings beside the real chapter run are left out."""
    styles = collections.defaultdict(list)
    for i, c in enumerate(cands):
        found = rules.number_key(c["label"])
        if found and found[0][0] == "chapter":
            styles[(found[0], bool(re.match(r"(?i)chapter\b", c["label"])))].append((i, found[1]))
    if len(styles) < 2:
        return cands
    main = max(len(v) for v in styles.values())
    drop = {
        i
        for v in styles.values()
        if len(v) <= 5 and len(v) * 3 <= main and all(n > 1 for _, n in v)
        for i, _ in v
    }
    return [c for i, c in enumerate(cands) if i not in drop]


def _join_title_pages(cands, ev):
    """A heading alone on its page and the heading opening the next page are one entry."""
    order = {doc.path: doc.index for doc in ev.story}
    counts = collections.Counter(rules.heading_key(c["label"]) for c in cands)
    out = []
    i = 0
    while i < len(cands):
        c = cands[i]
        n = cands[i + 1] if i + 1 < len(cands) else None
        if (
            n
            and c["alone"]
            and c["linkable"]
            and n["opens"]
            and order.get(n["path"], -9) == order.get(c["path"], -9) + 1
            and not any(
                rules.BACK_MATTER.match(x["label"]) or rules.SECTION_LABEL.match(x["label"])
                for x in (c, n)
            )
            and (
                (
                    counts[rules.heading_key(c["label"])] > 1
                    and not rules.chapterish(c["label"])
                    and rules.chapterish(n["label"])
                )
                or (
                    rules.chapter_number(c["label"]) is not None
                    and not rules.chapterish(n["label"])
                )
            )
        ):
            same = rules.heading_key(c["label"]).endswith(rules.heading_key(n["label"]))
            out.append(
                {
                    **c,
                    "label": c["label"] if same else c["label"] + ": " + n["label"],
                    "level": min(c["level"], n["level"]),
                    "joined": c["joined"] or (None if same else n["item"]["source"]),
                }
            )
            i += 2
            continue
        out.append(c)
        i += 1
    return out


def _two_levels(cands):
    """The book's top level and its chapter level, the linkable level with most headings."""
    levels = sorted({c["level"] for c in cands})
    if len(levels) <= 2:
        return cands, levels
    counts = collections.Counter(c["level"] for c in cands if c.get("native", c["linkable"]))
    sub = max(levels[1:], key=lambda level: (counts[level], -level))
    return [
        {**c, "level": min(c["level"], sub) if c["level"] > levels[0] else c["level"]}
        for c in cands
        if c["level"] <= sub
    ], [levels[0], sub]


def _entry(c, label=None, origin=None):
    return {
        "cand": c,
        "label": rules.plain_label(label or c["label"]),
        "origin": origin,
        "children": [],
    }


def _nest(cands, levels):
    """A Part, Book or story title holds the chapters that follow it (LF _nest)."""
    top = levels[0]
    sub = levels[1] if len(levels) > 1 else None
    follows = []
    run = None
    for c in cands:
        if c["level"] == top:
            run = [0] if not rules.SECTION_LABEL.match(c["label"]) else None
            follows.append(run)
        elif run is not None:
            run[0] += 1
    nest = sub is not None and sum(1 for r in follows if r and r[0] >= 2) >= 2
    entries: list[dict] = []
    holder = None
    partial: list[dict] = []
    tops: list[dict] = []
    back = None
    titles = set()
    for c in cands:
        if c["level"] == top:
            back = c["path"] if rules.BACK_MATTER.match(c["label"]) else None
        elif back == c["path"]:
            continue
        item = _entry(c)
        if nest and c["level"] == top:
            holder = item if c["linkable"] and not rules.SECTION_LABEL.match(c["label"]) else None
            if c["linkable"]:
                entries.append(item)
        elif nest and holder is not None and not rules.BACK_MATTER.match(c["label"]):
            if c["linkable"]:
                holder["children"].append(item)
            elif not any(x is holder for x in partial):
                partial.append(holder)
        elif c["linkable"]:
            if nest:
                holder = None
            if (
                not nest
                and c["level"] == sub
                and entries
                and entries[-1]["cand"]["path"] == c["path"]
                and any(entries[-1] is t for t in tops)
            ):
                entries[-1]["children"].append(item)
            else:
                entries.append(item)
                if c["level"] == top:
                    tops.append(item)
                if c["alone"] and not (
                    rules.chapterish(c["label"])
                    or rules.SECTION_LABEL.match(c["label"])
                    or rules.BACK_MATTER.match(c["label"])
                ):
                    titles.add(id(item))
    for h in partial:
        h["children"] = []
    if not nest:
        entries = _title_holders(entries, titles)

    def collapse(items):
        out: list[dict] = []
        for i in items:
            i["children"] = collapse(i["children"])
            if out and out[-1]["label"].lower() == i["label"].lower():
                out[-1]["children"] += i["children"]
                continue
            out.append(i)
        return out

    return _books(_split_book_chapters(collapse(entries)))


def _title_holders(entries, titles):
    """Novel titles alone on their pages hold the entries up to the next title."""
    at = [i for i, e in enumerate(entries) if id(e) in titles and not e["children"]]
    runs = []
    for k, i in enumerate(at):
        end = at[k + 1] if k + 1 < len(at) else len(entries)
        if k + 1 == len(at):
            close = next(
                (
                    j
                    for j in range(i + 1, end)
                    if re.match(r"(?i)(?:epilogue|afterword|coda)\b", entries[j]["label"])
                ),
                None,
            )
            end = (
                close + 1
                if close is not None
                else next(
                    (j for j in range(i + 1, end) if rules.BACK_MATTER.match(entries[j]["label"])),
                    end,
                )
            )
        runs.append((i, end))
    if sum(1 for i, end in runs if end - i - 1 >= rules.BOOK_ENTRIES) < 2:
        return entries
    out = entries[: at[0]]
    last = at[0]
    for i, end in runs:
        out += entries[last:i]
        title = entries[i]
        if end - i - 1 >= rules.BOOK_ENTRIES:
            title["children"] = entries[i + 1 : end]
            out.append(title)
        else:
            out += entries[i:end]
        last = end
    return out + entries[last:]


def _split_book_chapters(entries):
    """ "Book One: Chapter One" opens a book: "Book One" holding "Chapter One"."""
    out = []
    for e in entries:
        match = (
            rules.BOOK_CHAPTER.match(" ".join(e["label"].split())) if not e["children"] else None
        )
        if match:
            out += [
                {**e, "label": match.group(1), "origin": "split_heading", "children": []},
                {**e, "label": match.group(2), "origin": "split_heading", "children": []},
            ]
        else:
            out.append(e)
    return out


def _books(entries):
    """An omnibus whose novel titles are pictures: restarting chapter runs become books."""
    runs: list[list[dict]] = [[]]
    numbered = False
    for e in entries:
        if e["children"]:
            runs += [[e], []]
            numbered = False
            continue
        label = e["label"]
        prologue = bool(re.match(r"(?i)prologue\b", label))
        if rules.BARE_DIVISION.match(label) and runs[-1]:
            runs.append([])
            numbered = False
        if runs[-1] and numbered and (prologue or rules.FIRST_NUMBER.match(label)):
            runs.append([])
            numbered = False
        runs[-1].append(e)
        numbered = numbered or rules.numbered_label(label)
    if sum(1 for r in runs if len(r) >= rules.BOOK_ENTRIES) < 2:
        return entries

    def chapterish(e):
        return rules.numbered_label(e["label"]) or rules.SECTION_LABEL.match(e["label"])

    out: list[dict] = []
    n = 0
    for r in runs:
        first = next((k for k, e in enumerate(r) if chapterish(e)), len(r))
        last = max((k for k, e in enumerate(r) if chapterish(e)), default=-1)
        if last < 0:
            out += r
            continue
        lead, body, tail = r[:first], r[first : last + 1], r[last + 1 :]
        out += lead
        if len(body) >= rules.BOOK_ENTRIES:
            if (
                out
                and not chapterish(out[-1])
                and not out[-1]["children"]
                and not rules.BACK_MATTER.match(out[-1]["label"])
            ):
                out[-1]["children"] = body
            else:
                n += 1
                out.append(
                    {
                        "cand": body[0]["cand"],
                        "label": f"Book {n}",
                        "origin": "numbered_book",
                        "children": body,
                    }
                )
        else:
            out += body
        out += tail
    return out


def _count(entries):
    return sum(1 + _count(e["children"]) for e in entries)


def _walk(entries):
    for entry in entries:
        yield entry
        yield from _walk(entry["children"])


def _printed_entries(ev):
    """The book's printed contents page as a contents list, its links in reading order."""
    order = {doc.path: doc.index for doc in ev.story}
    for doc in ev.story:
        if not doc.printed_contents():
            continue
        out: list[dict] = []
        at = (-1, -1)
        for link in doc.item["links"]:
            if link.get("tag") != "a" or link.get("attribute") != "href":
                continue
            label = " ".join((link.get("label") or "").split())
            if not label or link.get("external"):
                continue
            dest, frag = link["target_path"], link["fragment"] or None
            if dest not in order or dest == doc.path:
                continue
            dash = re.match(r"^(.*\S)\s+[–—-]\s+(.+)$", label)
            if dash and rules.author_line(dash.group(2), ev.creators):
                label = dash.group(1)
            if (
                rules.NOT_A_CHAPTER.match(label)
                or rules.FRONT_LABEL.match(label)
                or rules.JUNK_LABEL.match(label)
                or rules.HEADING_JUNK.match(label)
                or rules.DEBRIS_LABEL.match(label)
                or rules.prose(label)
                or rules.author_line(label, ev.creators)
            ):
                continue
            _, position = ev.resolve(dest, frag)
            if position is None:
                continue
            # LF's spot is the text block an anchor opens: anchors with no words between them meet.
            here = (order[dest], position["word_offset"])
            if out and (
                (out[-1]["cand"]["path"], out[-1]["cand"]["fragment"]) == (dest, frag) or here == at
            ):
                if rules.heading_key(label) != rules.heading_key(out[-1]["label"]):
                    out[-1]["label"] += " " + label
                continue
            if here < at:
                return []
            if out and rules.heading_key(label) == rules.heading_key(out[-1]["label"]):
                continue
            at = here
            out.append(
                {
                    "cand": {
                        "path": dest,
                        "fragment": frag,
                        "anchor": False,
                        "position": position,
                        "label_doc": doc,
                        "label_index": link["source_index"],
                    },
                    "label": label,
                    "origin": "printed_link",
                    "children": [],
                }
            )
        return out
    return []


def _story_start(ev):
    """The first page of the story itself: the first longer than a front page, else the longest."""
    pages = [doc for doc in ev.story if doc.words]
    if not pages:
        return None
    return next(
        (d for d in pages if d.words > rules.FRONT_SHORT), max(pages, key=lambda d: d.words)
    )


def _single_story(ev):
    start = _story_start(ev)
    if not (start and ev.title):
        return []
    return [
        {
            "cand": {
                "path": start.path,
                "fragment": None,
                "anchor": False,
                "position": {"source_index": 0, "word_offset": 0},
                "label_doc": None,
            },
            "label": ev.title,
            "origin": "book_title",
            "children": [],
        }
    ]


class _Existing:
    """The book's own lists as LF reads them, from recorded NAV and NCX entries."""

    def __init__(self, report, ev):
        rows = report["navigation"]["entries"]
        if len(rows) > MAX_ENTRIES:
            raise _Held("output_limit")
        self.rows = rows
        self.observations = []
        for row in rows:
            if not isinstance(row.get("label"), str):
                raise _Held("source_evidence_unavailable")
            if len(row.get("ancestors", [])) >= MAX_DEPTH:
                raise _Held("hierarchy_limit")
            self.observations.append(
                {
                    "label": row["label"],
                    "path": row["target_path"],
                    "fragment": row["fragment"] or None,
                    "kind": row["kind"],
                    "ancestors": list(row.get("ancestors", [])),
                }
            )
        ncx = [row for row in rows if row["kind"] == "ncx"]
        nav = [row for row in rows if row["kind"] == "nav"]
        self.lists = [rows for rows in (ncx, nav) if rows]
        self.primary = ncx if ncx else nav
        self.labels = [
            " ".join(row["label"].split())
            for row in self.primary
            if not rules.junk_entry(row["label"])
        ]
        self.shown = [
            " ".join(row["label"].split()) for row in nav if not rules.junk_entry(row["label"])
        ]
        self.size = max(len(ncx), len(nav))
        named = sum(
            1
            for label in self.labels
            if rules.BYLINE.match(label)
            and (rules.author_line(label, ev.creators) or len(label.split()) <= 3)
        )
        self.navigation_sound = (
            not (ev.epub3 and not report["navigation"]["nav_paths"]) and not ev.navigation_errors
        )
        self.sound = (
            not rules.numbering_problems([(label, 0) for label in self.labels])
            and not (named >= 2 and named * 3 >= len(self.labels))
            and self._in_order(ev)
        )
        self.clean = (
            self.sound
            and rules.clean_list(self.labels)
            and (not self.shown or rules.clean_list(self.shown))
            and self.navigation_sound
        )
        self.existing = max(len(self.labels), self.size)

    def _in_order(self, ev):
        at = (-1, -1)
        for row in self.primary:
            doc, position = ev.resolve(row["target_path"], row["fragment"])
            if doc is None:
                continue
            # LF (_list_in_order) reads an unknown fragment as its page's start and compares
            # the text blocks entries open, so anchors with no words between them are level.
            here = (doc.index, position["word_offset"] if position is not None else 0)
            if here < at:
                return False
            at = here
        return True

    def matches(self, ev, entries):
        """Every list the book has equals the proposal: same labels, levels and places."""
        return bool(self.lists) and all(self._same(ev, entries, rows) for rows in self.lists)

    @staticmethod
    def _same(ev, entries, rows):
        proposed = list(_depths(entries))
        if len(proposed) != len(rows):
            return False
        for (entry, depth), row in zip(proposed, rows, strict=True):
            if _fold(entry["label"]) != _fold(row["label"]) or depth != len(
                row.get("ancestors", [])
            ):
                return False
            doc, position = ev.resolve(row["target_path"], row["fragment"])
            target = _position(entry, ev)
            if doc is None or position is None or doc.path != entry["cand"]["path"]:
                return False
            if (row["fragment"] or None) != entry["cand"]["fragment"] and any(
                position.get(field, 0) != target.get(field, 0)
                for field in ("word_offset", "non_heading_word_offset", "media_offset")
            ):
                return False
        return True


def _depths(entries, depth=0):
    for entry in entries:
        yield entry, depth
        yield from _depths(entry["children"], depth + 1)


def _position(entry, ev):
    c = entry["cand"]
    if "position" in c:
        return c["position"]
    source = c["item"]["source"]
    if c["fragment"] and not c["anchor"] and c["fragment"] in ev.by_path[c["path"]].anchors:
        anchor = ev.by_path[c["path"]].anchors[c["fragment"]]
        if anchor["word_offset"] == source["word_offset"]:
            return anchor
    return source


def _section_words(ev, entries):
    """Words from each flattened entry's start to the next start, in reading order."""
    flat = [entry for entry in _walk(entries)]
    starts = []
    offsets = []
    total = 0
    for doc in ev.story:
        offsets.append(total)
        total += doc.words
    for entry in flat:
        doc = ev.by_path[entry["cand"]["path"]]
        starts.append(offsets[doc.index] + _position(entry, ev)["word_offset"])
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1])
    return flat, [
        (starts[i + 1] if i + 1 < len(starts) else total) - starts[i] for i in range(len(starts))
    ]


def _drop_trailing_stubs(ev, entries):
    """A last part or book title with nothing under it and a teaser's words is left out."""
    if len(entries) < 2 or ev.words <= rules.LONG_BOOK:
        return entries
    last = entries[-1]
    if last["children"] or not re.match(r"(?i)(?:part|book)\b", last["label"]):
        return entries
    _, words = _section_words(ev, entries)
    return entries[:-1] if words[-1] < rules.TRAILING_WORDS else entries


def _big_section(ev, entries):
    """(label, words) of the first entry with nothing under it that holds too many words."""
    flat, words = _section_words(ev, entries)
    if len(flat) < 2:
        return None
    for entry, count in zip(flat, words, strict=True):
        if not entry["children"] and count > rules.BIG_SECTION:
            return entry["label"], count
    return None


class _Decision(Exception):
    def __init__(self, decision, reasons, entries=()):
        super().__init__(decision)
        self.decision, self.reasons, self.entries = decision, reasons, list(entries)


def _decide(report, ev):
    """keep, rebuild or refuse the contents list by LF's rules (_contents_plan)."""
    cands = _drop_stray_numbers(_fill_chapter_gaps(ev, _heading_candidates(ev)))
    cands, levels = _two_levels(_join_title_pages(cands, ev))
    entries = _nest(cands, levels) if cands else []
    existing = _Existing(report, ev)
    labels = existing.labels
    headings = len(cands)
    linked = sum(1 for c in cands if c["linkable"])
    words = ev.words
    measures = {
        "existing": existing.existing,
        "headings": headings,
        "linked": linked,
        "entries": _count(entries),
        "words": words,
    }
    problems: list[str] = []

    def say(decision, reason, chosen=()):
        reasons = [reason]
        if decision == "held" and ev.scan:
            reasons.append("ocr_scan")
        return decision, reasons, list(chosen), measures, problems

    if existing.clean and headings and abs(len(labels) - headings) * 10 <= headings:
        return say("keep", "existing_matches_headings")
    if (
        existing.sound
        and entries
        and 2 * _count(entries) < existing.existing
        and existing.navigation_sound
    ):
        return say("keep", "rebuild_far_shorter")
    if existing.clean and _count(entries) < min(rules.MIN_CHAPTERS, len(labels)):
        return say("keep", "rebuild_too_short")
    if min(linked, _count(entries)) < rules.MIN_CHAPTERS and (
        words > rules.LONG_BOOK or not entries
    ):
        if existing.clean:
            return say("keep", "no_usable_headings")
        if not headings:
            reason = "no_chapter_headings"
        elif headings < rules.MIN_CHAPTERS:
            reason = "too_few_headings"
        elif linked < rules.MIN_CHAPTERS:
            reason = "unlinkable_headings"
        else:
            reason = "too_few_entries"
        printed = _printed_entries(ev)
        if len(printed) >= rules.MIN_CHAPTERS or (printed and words <= rules.LONG_BOOK):
            return say("propose", "printed_contents", printed)
        if words <= rules.LONG_BOOK:
            single = _single_story(ev)
            if single:
                return say("propose", "single_story", single)
        return say("held", reason)
    printed = _printed_entries(ev)
    if len(printed) >= rules.MIN_CHAPTERS and len(printed) >= 2 * _count(entries):
        return say("propose", "printed_contents", printed)
    flat = [
        (entry["label"], depth, ev.by_path[entry["cand"]["path"]].index)
        for entry, depth in _depths(entries)
    ]
    problems = rules.numbering_problems(flat)[:MAX_PROBLEMS]
    if problems:
        if words <= rules.LONG_BOOK:
            short = printed or _single_story(ev)
            if short:
                return say("propose", "printed_contents" if printed else "single_story", short)
        return say("held", "numbering_unsettled")
    entries = _drop_trailing_stubs(ev, entries)
    measures["entries"] = _count(entries)
    big = _big_section(ev, entries)
    if big:
        problems = [f'"{big[0]}" holds {big[1]:,} words with nothing under it']
        return say("held", "missed_chapters")
    return say("propose", "chapter_headings", entries)


def _source(entry, ev):
    """The plan entry: exact target position, link fragment and label source."""
    c = entry["cand"]
    doc = ev.by_path[c["path"]]
    position = _position(entry, ev)
    if "position" in c:
        label_doc = c["label_doc"]
        label_source = (
            {
                "path": label_doc.path,
                "source_index": c["label_index"],
                "document_sha256": label_doc.sha,
            }
            if label_doc is not None
            else {
                "path": ev.package["path"],
                "source_index": 0,
                "document_sha256": ev.package["byte_sha256"],
            }
        )
        origin = entry["origin"]
    else:
        label_source = {
            "path": doc.path,
            "source_index": c["item"]["pos"],
            "document_sha256": doc.sha,
        }
        origin = entry["origin"] or (
            "joined_label"
            if c["joined"] is not None
            else "heading"
            if c["item"]["kind"] == "heading"
            else "paragraph"
        )
    return {
        "label": entry["label"],
        "path": doc.path,
        "fragment": None if c["anchor"] else c["fragment"],
        "requires_anchor": c["anchor"],
        "origin": origin,
        "position": {
            "document_index": doc.index,
            "source_index": position["source_index"],
            "word_offset": position["word_offset"],
            "document_sha256": doc.sha,
        },
        "label_source": label_source,
        "children": [_source(child, ev) for child in entry["children"]],
    }


def _depth(entries, depth=1):
    return max((max(depth, _depth(e["children"], depth + 1)) for e in entries), default=0)


def contents_plan(report, *, record=None):
    result = held_plan(report, "source_evidence_unavailable")
    try:
        evidence = _Evidence(report)
        existing = _Existing(report, evidence)
        result["existing"] = existing.observations
        decision, reasons, entries, measures, problems = _decide(report, evidence)
        if (
            decision == "propose"
            and existing.navigation_sound
            and existing.matches(evidence, entries)
        ):
            decision, reasons, entries = "keep", ["existing_matches_rebuild"], []
        built = [_source(entry, evidence) for entry in entries]
        if len(existing.observations) + sum(1 for _ in _walk(built)) > MAX_ENTRIES:
            raise _Held("output_limit")
        if _depth(built) > MAX_DEPTH:
            raise _Held("hierarchy_limit")
        if decision == "keep" and not existing.observations:
            decision, reasons, built = "held", ["unsupported_structure"], []
        result.update(
            decision=decision,
            reason_codes=reasons,
            measures=measures,
            problems=problems,
            entries=built,
            excluded_targets=[],
        )
    except _Held as error:
        result.update(decision="held", reason_codes=[str(error)], entries=[], excluded_targets=[])
    except KeyError, TypeError, ValueError, IndexError, AttributeError:
        result.update(
            decision="held",
            reason_codes=["source_evidence_unavailable"],
            entries=[],
            excluded_targets=[],
        )
    if record is not None:
        for item in [*result["existing"], *_walk(result["entries"]), *result["excluded_targets"]]:
            record(item)
    return result
