"""Pure cover rules ported from Library Finish; see cover_sources_provenance.json."""

import difflib
import re
import unicodedata

from bl_catalog.resolve import titles as catalogue_titles
from PIL import Image, ImageStat

MIN_W = 1000


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def similarity(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        # a contained title ("Horus Rising" in "Horus Rising: The Horus Heresy Book 1") is a strong match,
        # but only an exact one is perfect: "Legion" must not tie with "DC Comics Presents Legion of ..."
        return max(ratio, 0.75 + 0.25 * min(len(a), len(b)) / max(len(a), len(b)))
    return ratio


def title_fit(book_title, book_author, cand_title):
    """0..1 for how well a provider title names this book; 0.0 means a clearly different work.

    Reuses the BL Catalog edition-key matcher, which is lenient by design: decorated and
    truncated titles stay above zero. A collection word is dropped from both sides, so an
    omnibus of the same title stays a candidate for `kind_mismatch` to refuse and say why.
    A title that cannot be judged (either side blank) is not rejected.
    """

    def key(title):
        words = catalogue_titles.title_key(str(title or "")).split()
        return " ".join(w for w in words if w not in catalogue_titles.COLLECTION_WORDS)

    mine, theirs = key(book_title), key(cand_title)
    if not mine or not theirs:
        return 1.0
    context = catalogue_titles.context_words(authors=[book_author] if book_author else [])
    return catalogue_titles.key_compatibility(mine, theirs, context)


def isbn13(v):
    """A valid ISBN (10 or 13, any punctuation) -> its ISBN-13, else None."""
    v = re.sub(r"[^0-9Xx]", "", str(v or "")).upper()
    if len(v) == 10:
        if (
            not re.fullmatch(r"\d{9}[\dX]", v)
            or sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(v)) % 11
        ):
            return None
        v = "978" + v[:9]
        v += str(-sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(v)) % 10)
    if (
        not re.fullmatch(r"\d{13}", v)
        or sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(v)) % 10
    ):
        return None
    return v


def _title_forms(t):
    """'Ciaphas Cain: Hero of the Imperium (Omnibus)' -> {whole, 'hero of the imperium', 'ciaphas cain'}, series tags dropped."""
    t = re.sub(r"\s*[\(\[][^()\[\]]*[\)\]]", "", t or "")
    forms = {norm(t)} | {norm(x) for x in re.split(r"\s*:\s*", t) if len(norm(x)) >= 4}
    return {f for f in forms if f}


def isbn_match(title, author, c):
    """Is candidate c the same work as the book, strictly enough to borrow its ISBN? One whole title must
    equal the other's whole title, main title or subtitle (a contained title is NOT enough: 'Trollslayer'
    is inside the Gotrek & Felix omnibus title, and a shared 'Series:' prefix is not the same book),
    and the first author must agree."""
    ft, fc = _title_forms(title), _title_forms(c.get("title"))
    whole = lambda t: norm(re.sub(r"\s*[\(\[][^()\[\]]*[\)\]]", "", t or ""))
    if whole(title) not in fc and whole(c.get("title")) not in ft:
        return False
    first = lambda x: (
        norm(re.sub(r"^\s*([^,&]+?)\s*,\s*([^,&]+?)\s*$", r"\2 \1", x.split("&")[0])) if x else ""
    )
    a, ca = (
        first(author),
        [first(x) for x in re.split(r"\s*(?:&|;|, (?=\S+ \S))\s*", c.get("author") or "") if x],
    )
    return bool(a) and any(similarity(a, x) >= 0.85 for x in ca)


def english_isbn(vals):
    """First valid English-language (978-0 / 978-1) ISBN in vals: the same rule isbncheck adds by."""
    for v in vals or []:
        n = isbn13(v)
        if n and n.startswith(("9780", "9781")):
            return n
    return None


def apple_hires(u):
    return [re.sub(r"/\d+x\d+bb\.(jpg|png|webp)$", "/1600x1600bb.jpg", u)]


def problem(im):
    w, h = im.size
    if w < 120 or h < 160:
        return "too small"
    if not 0.45 <= w / h <= 1.1:  # audio drama covers are square or a touch wider (650x640)
        return "not cover-shaped"
    if ImageStat.Stat(im.convert("L").resize((48, 72))).stddev[0] < 10:
        return "blank placeholder"
    return None


def fingerprint(im):
    """Tiny grayscale layout + coarse colour grid: enough to tell 'same artwork' apart."""
    im = im.convert("RGB")
    g = list(im.convert("L").resize((24, 36), Image.Resampling.BILINEAR).getdata())
    mean = sum(g) / len(g)
    g = [v - mean for v in g]
    norm_ = sum(v * v for v in g) ** 0.5 or 1.0
    col = [v / 255 for px in im.resize((4, 6), Image.Resampling.BILINEAR).getdata() for v in px]
    return {"g": [v / norm_ for v in g], "c": col}


def look_alike(a, b):
    """0..1: how much two covers look like the same artwork (layout correlation + colour)."""
    corr = sum(x * y for x, y in zip(a["g"], b["g"]))
    cdist = sum(abs(x - y) for x, y in zip(a["c"], b["c"])) / len(a["c"])
    return max(0.0, 0.7 * corr + 0.3 * (1 - 2 * cdist))


def score(cands, title, author):
    for c in cands:
        c["match"] = (
            round(
                0.7 * similarity(title, c["title"])
                + 0.3 * (similarity(author.split("&")[0], c["author"]) if author else 0.5),
                2,
            )
            if title
            else None
        )
        c["needs_upscale"] = c["width"] < MIN_W
        if c.get("isbn") and not isbn_match(title, author, c):
            c["isbn"] = None


COLLECTION = re.compile(
    r"\b(omnibus|anthology|collection|collected|compendium|trilogy|duology|quartet|quintet|"
    r"box(ed)? ?set|the complete|stories|tales|books? \d+\s*[-–&]\s*\d+)\b",
    re.IGNORECASE,
)


def kind_mismatch(book_title, cand_title):
    if not book_title or not cand_title:
        return None
    mine, theirs = bool(COLLECTION.search(book_title)), bool(COLLECTION.search(cand_title))
    return (
        "Omnibus cover"
        if theirs and not mine
        else "Single-book cover"
        if mine and not theirs
        else None
    )


def rank(cands, current_fp, title=None):
    """Put the best pick first and say why.
    Real (small) current cover: the candidate that looks most like it, so the same edition's
    artwork is kept. Generated placeholder / no cover: strongest identity (ISBN hit, then
    title/author match), resolution breaks ties."""
    for c in cands:
        c["look"] = round(look_alike(current_fp, c["_fp"]), 2) if current_fp else None
        c["kind_mismatch"] = kind_mismatch(title, c.get("title"))
    # A caller may mark a candidate `_weak`: it keeps its place in the list but is never the pick.
    eligible = lambda c: not c["kind_mismatch"] and not c.get("_weak")
    # Wrong kind (omnibus vs single book) always sorts below every right-kind candidate.
    ident = lambda c: (
        not c["kind_mismatch"],
        c["by_isbn"] and (c["match"] or 0) >= 0.6,
        (c["match"] or 0) >= 0.75,
        c["match"] or 0,
        c["height"],
    )
    cands.sort(key=ident, reverse=True)
    best = None
    if current_fp:
        alike = [c for c in cands if c["look"] >= 0.6 and eligible(c)]
        if alike:
            best = max(alike, key=lambda c: (round(c["look"], 1), c["height"]))
            best["why"] = f"Closest to the current cover ({round(best['look'] * 100)}% alike)"
    if best is None:
        best = next((c for c in cands if eligible(c)), None)
    if best is not None and "why" not in best:
        best["why"] = (
            "ISBN match"
            if best["by_isbn"] and (best["match"] or 0) >= 0.6
            else "Best title/author match"
        )
    if best:
        cands.remove(best)
        cands.insert(0, best)
        best["recommended"] = True
    for c in cands:
        c.setdefault(
            "why",
            c["kind_mismatch"]
            or (
                "ISBN lookup; confirm the edition visually"
                if c["by_isbn"]
                else "Title and author search; confirm visually"
            ),
        )
        c.pop("_fp", None)
    return cands
