"""Prepare disposable synthetic state and verify the assessment API with a real worker."""

import argparse
import hashlib
import io
import ipaddress
import json
import sqlite3
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = "librarium.synthetic-assessment-acceptance.v1"
VERSION = "2026.10.29.1"
WORK = "w_fixture"
EDITION = "e_fixture"
TITLE = "Fixture: The Glass Meridian"
AUTHOR = "Fixture Author"
REFERENCE = "synthetic.reference-1"
AUTHORITY = "synthetic.authority"
MAX_FILE = 32 * 1024 * 1024
MAX_REPLY = 2 * 1024 * 1024
ACCEPTED = (200, 202)
SOURCE_DIRS = ("library", "catalogue", "trust", "inputs")

CATALOGUE_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE work(id TEXT PRIMARY KEY,title TEXT,sort_title TEXT,synopsis TEXT,type TEXT,
                  first_published TEXT,setting TEXT,word_count INTEGER,length_class TEXT);
CREATE TABLE author(id INTEGER PRIMARY KEY,name TEXT,sort_name TEXT);
CREATE TABLE author_alias(author_id INTEGER,name TEXT);
CREATE TABLE work_author(work_id TEXT,author_id INTEGER,role TEXT);
CREATE TABLE series(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE work_series(work_id TEXT,series_id INTEGER,position REAL);
CREATE TABLE edition(id TEXT PRIMARY KEY,work_id TEXT,format TEXT,isbn10 TEXT,isbn13 TEXT,
                     publisher TEXT,release_date TEXT);
CREATE TABLE edition_ident(edition_id TEXT,kind TEXT,value TEXT,status TEXT);
CREATE TABLE work_ident(work_id TEXT,kind TEXT,value TEXT);
CREATE TABLE work_alias(work_id TEXT,title TEXT);
CREATE TABLE work_contains(parent_id TEXT,child_id TEXT,position INTEGER);
CREATE TABLE work_tag(work_id TEXT,kind TEXT,value TEXT);
CREATE TABLE field_support(entity TEXT,entity_id TEXT,field TEXT,value TEXT,score REAL,
                           agree_json TEXT,disagree_json TEXT);
CREATE TABLE harvest_log(id INTEGER PRIMARY KEY,source TEXT,query TEXT,status TEXT,
                         http_status INTEGER,fetched_at TEXT);
CREATE TABLE id_alias(old_id TEXT PRIMARY KEY,new_id TEXT);
"""

LIBRARY_SCHEMA = """
CREATE TABLE books(id INTEGER PRIMARY KEY,title TEXT,sort TEXT,path TEXT,uuid TEXT,
                   series_index REAL,pubdate TEXT,timestamp TEXT,last_modified TEXT,has_cover INTEGER);
CREATE TABLE authors(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE books_authors_link(id INTEGER PRIMARY KEY,book INTEGER,author INTEGER);
CREATE TABLE series(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE books_series_link(id INTEGER PRIMARY KEY,book INTEGER,series INTEGER);
CREATE TABLE publishers(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE books_publishers_link(id INTEGER PRIMARY KEY,book INTEGER,publisher INTEGER);
CREATE TABLE languages(id INTEGER PRIMARY KEY,lang_code TEXT);
CREATE TABLE books_languages_link(id INTEGER PRIMARY KEY,book INTEGER,lang_code INTEGER,item_order INTEGER);
CREATE TABLE identifiers(id INTEGER PRIMARY KEY,book INTEGER,type TEXT,val TEXT);
CREATE TABLE data(id INTEGER PRIMARY KEY,book INTEGER,format TEXT,uncompressed_size INTEGER,name TEXT);
CREATE TABLE comments(id INTEGER PRIMARY KEY,book INTEGER,text TEXT);
CREATE TABLE library_id(id INTEGER PRIMARY KEY,uuid TEXT);
"""


class ProofError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ProofError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2).encode()


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    path.chmod(0o444)


def source_bytes(*, changed=False):
    first = "Original synthetic story sentence."
    if changed:
        first = "Ori<em>ginal</em>  synthetic story sentence."
    second = "Changed synthetic ending." if changed else "Original synthetic ending."
    page = lambda body: (
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Fixture</title></head>'
        f"<body>{body}</body></html>"
    )
    files = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "book.opf": f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book">urn:isbn:9780306406157</dc:identifier><dc:title>{TITLE}</dc:title><dc:creator>{AUTHOR}</dc:creator><dc:language>en</dc:language></metadata><manifest><item id="first" href="first.xhtml" media-type="application/xhtml+xml"/><item id="second" href="second.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="first"/><itemref idref="second"/></spine></package>',
        "first.xhtml": page(
            f'<section epub:type="titlepage"><p epub:type="title">{TITLE}</p>'
            f'<p epub:type="author">{AUTHOR}</p></section>'
            f'<h1 id="one">Chapter 1</h1><p>{first}</p>'
        ),
        "second.xhtml": page(f'<h1 id="two">Chapter 2</h1><p>{second}</p>'),
        "nav.xhtml": page(
            '<nav epub:type="toc"><ol><li><a href="first.xhtml#one">One</a></li><li><a href="second.xhtml#two">Two</a></li></ol></nav>'
        ),
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, text in files.items():
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            archive.writestr(entry, text.encode())
    return stream.getvalue()


def prepare_catalogue(root):
    path = root / "catalogue" / f"{VERSION}.sqlite"
    path.parent.mkdir()
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(CATALOGUE_SCHEMA)
        db.execute("INSERT INTO meta VALUES('catalog_version',?)", (VERSION,))
        db.execute(
            "INSERT INTO work(id,title,synopsis,type) VALUES(?,?,?,'novel')",
            (WORK, TITLE, "Synthetic acceptance fixture"),
        )
        db.execute("INSERT INTO author VALUES(1,?,?)", (AUTHOR, AUTHOR))
        db.execute("INSERT INTO work_author VALUES(?,1,'author')", (WORK,))
        db.execute("INSERT INTO series VALUES(1,'Fixture Series')")
        db.execute("INSERT INTO work_series VALUES(?,1,1)", (WORK,))
        db.execute(
            "INSERT INTO edition(id,work_id,format,isbn13) VALUES(?,?,'epub','9780306406157')",
            (EDITION, WORK),
        )
    path.chmod(0o444)
    put(path.parent / "current", VERSION.encode())
    return {"version": VERSION, "sha256": sha(path.read_bytes())}


def prepare_library(root, raw, library_uuid):
    directory = root / "library"
    directory.mkdir()
    with closing(sqlite3.connect(directory / "metadata.db")) as db, db:
        db.executescript(LIBRARY_SCHEMA)
        db.execute("INSERT INTO library_id VALUES(1,?)", (library_uuid,))
        db.execute("INSERT INTO authors VALUES(1,?)", (AUTHOR,))
        for book in (1, 2):
            folder = f"Fixture Author/Proof book ({book})"
            name = f"Proof book {book}"
            db.execute(
                "INSERT INTO books(id,title,sort,path,uuid,series_index,has_cover) VALUES(?,?,?,?,?,1,0)",
                (book, TITLE, TITLE, folder, f"synthetic-proof-book-{book}"),
            )
            db.execute("INSERT INTO books_authors_link VALUES(?,?,1)", (book, book))
            db.execute("INSERT INTO data VALUES(?,?,'EPUB',?,?)", (book, book, len(raw), name))
            put(directory / folder / f"{name}.epub", raw)
        other = b"Synthetic other-format bytes; no PDF conformance claim."
        db.execute("INSERT INTO data VALUES(3,1,'PDF',?,'Proof other format')", (len(other),))
        put(directory / "Fixture Author/Proof book (1)/Proof other format.pdf", other)
    (directory / "metadata.db").chmod(0o444)


def prepare_trust(root, raw, pin):
    directory = root / "trust"
    directory.mkdir()
    issued = datetime.now(UTC) - timedelta(minutes=1)
    until = issued + timedelta(days=2)
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    evidence = {}
    for name in ("receipt", "publication", "coverage", "constituent"):
        data = encoded({"synthetic": True, "kind": name, "work_id": WORK})
        evidence[name] = sha(data)
        put(directory / "evidence" / sha(data), data)
    put(directory / "artifacts" / sha(raw), raw)
    manifest = {
        "schema": "librarium.complete-content-reference.v1",
        "reference_id": REFERENCE,
        "authority_id": AUTHORITY,
        "issued_at": stamp(issued),
        "valid_until": stamp(until),
        "artifact": {"sha256": sha(raw), "size": len(raw), "format": "epub"},
        "publication": {
            "catalogue_version": pin["version"],
            "catalogue_sha256": pin["sha256"],
            "work_id": WORK,
            "edition_id": EDITION,
            "language": "en",
            "revision": "synthetic-1",
            "scope": "standalone_work",
        },
        "acquisition": {
            "method": "synthetic_fixture",
            "acquired_at": stamp(issued),
            "source_lineage_id": "synthetic.lineage",
            "receipt_sha256": evidence["receipt"],
            "publication_evidence_sha256": evidence["publication"],
        },
        "coverage": {
            "protocol": "librarium.complete-reference-curation.v1",
            "record_sha256": evidence["coverage"],
            "expected_constituents": [
                {"work_id": WORK, "position": 1, "evidence_sha256": evidence["constituent"]}
            ],
            "unsupported_components": [],
        },
    }
    manifest_bytes = encoded(manifest)
    put(directory / "manifests" / f"{sha(manifest_bytes)}.json", manifest_bytes)
    registry = {
        "schema": "librarium.content-trust-registry.v1",
        "registry_id": "synthetic.registry",
        "revision": 1,
        "issued_at": stamp(issued),
        "valid_until": stamp(until),
        "authorities": [
            {
                "authority_id": AUTHORITY,
                "method": "operator_curated_local_reference",
                "scope": [
                    "work_identity",
                    "complete_collection",
                    "edition_identity",
                    "language",
                    "revision",
                ],
                "valid_from": stamp(issued),
                "valid_until": stamp(until),
                "revoked_at": None,
            }
        ],
        "references": [
            {
                "reference_id": REFERENCE,
                "authority_id": AUTHORITY,
                "manifest_sha256": sha(manifest_bytes),
            }
        ],
        "revocations": [],
    }
    registry_bytes = encoded(registry)
    put(directory / "registry.json", registry_bytes)
    return {
        "reference_id": REFERENCE,
        "registry_sha256": sha(registry_bytes),
        "manifest_sha256": sha(manifest_bytes),
    }


def source_hashes(root):
    values = {}
    for name in SOURCE_DIRS:
        directory = root / name
        require(
            directory.is_dir() and not directory.is_symlink(),
            "Synthetic source directory is unavailable",
        )
        for path in directory.rglob("*"):
            require(not path.is_symlink(), "Synthetic sources contain a symlink")
            if path.is_file():
                require(
                    stat.S_ISREG(path.stat().st_mode) and path.stat().st_size <= MAX_FILE,
                    "Synthetic source exceeds its file bound",
                )
                with path.open("rb") as stream:
                    values[path.relative_to(root).as_posix()] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
    return values


def environment(root, fixture, *, trust=True):
    return {
        "LIBRARIUM_DIRECT_LIBRARY_ROOT": str(root / "library"),
        "LIBRARIUM_CATALOGUE_DIR": str(root / "catalogue"),
        "LIBRARIUM_CATALOGUE_FIXTURE": "1",
        "LIBRARIUM_ARTIFACT_DIR": str(root / "artifacts"),
        "LIBRARIUM_CONTENT_TRUST_REGISTRY": str(root / "trust/registry.json") if trust else "",
        "LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256": fixture["reference"]["registry_sha256"]
        if trust
        else "",
        "LIBRARIUM_LIBRARY_URL": "",
        "LIBRARIUM_REFERENCE_STATE_DIR": "",
        "LIBRARIUM_PUBLIC_ORIGIN": "",
        "LIBRARIUM_TRUST_PROXY": "0",
    }


def prepare(path):
    path = Path(path)
    require(not path.is_symlink(), "Proof root must not be a symlink")
    require(
        not path.exists() or (path.is_dir() and not any(path.iterdir())),
        "Proof root must be fresh or empty",
    )
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = path.resolve()
    path.chmod(0o700)
    run_id = str(uuid.uuid4())
    library_uuid = str(uuid.uuid5(uuid.UUID(run_id), "synthetic-library"))
    raw, changed = source_bytes(), source_bytes(changed=True)
    pin = prepare_catalogue(path)
    prepare_library(path, raw, library_uuid)
    put(path / "inputs/original.epub", raw)
    put(path / "inputs/changed.epub", changed)
    reference = prepare_trust(path, raw, pin)
    (path / "artifacts").mkdir(mode=0o700)
    fixture = {
        "schema": SCHEMA,
        "run_id": run_id,
        "library_uuid": library_uuid,
        "catalogue": pin,
        "work_id": WORK,
        "reference": reference,
        "source_sha256": sha(raw),
        "changed_sha256": sha(changed),
        "hashes": source_hashes(path),
    }
    put(path / "fixture.json", encoded(fixture))
    (path / "environment.json").write_bytes(encoded(environment(path, fixture)))
    (path / "environment-unconfigured.json").write_bytes(
        encoded(environment(path, fixture, trust=False))
    )
    for name in ("environment.json", "environment-unconfigured.json"):
        (path / name).chmod(0o600)
    return fixture


def load_fixture(path):
    root = Path(path)
    require(not root.is_symlink(), "Proof root must not be a symlink")
    root = root.resolve()
    marker = root / "fixture.json"
    require(
        marker.is_file() and not marker.is_symlink() and marker.stat().st_size <= 64 * 1024,
        "Synthetic fixture marker is unavailable",
    )
    value = json.loads(marker.read_text())
    require(
        isinstance(value, dict) and value.get("schema") == SCHEMA,
        "Not an assessment acceptance fixture",
    )
    uuid.UUID(value["run_id"])
    require(
        value.get("work_id") == WORK and value.get("catalogue", {}).get("version") == VERSION,
        "Synthetic fixture identity does not match",
    )
    require(
        source_hashes(root) == value.get("hashes"), "Synthetic originals changed before acceptance"
    )
    return root, value


def local_url(value):
    url = urllib.parse.urlsplit(value)
    try:
        address = ipaddress.ip_address(url.hostname or "")
    except ValueError:
        raise ProofError("Acceptance URL must use a literal loopback address") from None
    require(
        url.scheme == "http"
        and address.is_loopback
        and not url.username
        and not url.password
        and url.path in {"", "/"}
        and not url.query
        and not url.fragment,
        "Acceptance URL must be a plain HTTP loopback origin",
    )
    try:
        require(
            url.port is not None and 1 <= url.port <= 65535, "Acceptance URL needs an explicit port"
        )
    except ValueError:
        raise ProofError("Acceptance URL port is invalid") from None
    return value.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ProofError("Acceptance refuses redirects")


class Client:
    def __init__(self, base_url):
        self.base = local_url(base_url)
        self.csrf = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, data=None, *, key=None, upload=False, expected=200):
        headers = {"Origin": self.base}
        if data is not None:
            require(self.csrf is not None, "Acceptance session must be established first")
            headers.update({"X-CSRFToken": self.csrf, "Cookie": f"librarium_csrftoken={self.csrf}"})
            if key is not None:
                headers["Idempotency-Key"] = str(key)
            if upload:
                headers.update(
                    {
                        "Content-Type": "application/epub+zip",
                        "X-Source-SHA256": sha(data),
                        "X-Source-Name": "Synthetic%20acceptance.epub",
                    }
                )
            else:
                headers["Content-Type"] = "application/json"
                data = encoded(data)
        # A replayed accepted mutation may answer 200 where its first acceptance said 202.
        accepted = {expected} if isinstance(expected, int) else set(expected)
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=10) as reply:
                require(reply.status in accepted, "Acceptance response status did not match")
                body = reply.read(MAX_REPLY + 1)
        except urllib.error.HTTPError as error:
            # An expected refusal is evidence; any other refusal stops the proof.
            with error:
                if error.code not in accepted:
                    raise ProofError(
                        f"Acceptance API refused a request (HTTP {error.code})"
                    ) from None
                body = error.read(MAX_REPLY + 1)
        require(len(body) <= MAX_REPLY, "Acceptance response exceeded its bound")
        return json.loads(body)

    def wait(self, job, *, seconds=90, state="succeeded"):
        deadline = time.monotonic() + seconds
        while job["state"] in {"queued", "running"}:
            require(
                time.monotonic() < deadline,
                "Independent worker did not finish within acceptance bound",
            )
            time.sleep(0.2)
            job = self.request(f"/api/jobs/{job['id']}")
        require(job["state"] == state, "Independent worker did not complete the acceptance job")
        return job


def connect(root, base_url):
    """Bind the client to this fixture's server before any mutation is sent."""
    root, fixture = load_fixture(root)
    client = Client(base_url)
    session = client.request("/api/session")
    listing = client.request("/api/direct-library")
    current = client.request("/api/catalogue")
    require(
        session.get("direct_library") is True and session.get("file_inspections") is True,
        "Synthetic assessment roles are unavailable",
    )
    require(
        listing.get("inventory", {}).get("library_uuid") == fixture["library_uuid"]
        and listing.get("total") == 2,
        "Server does not expose this synthetic library",
    )
    require(
        current.get("fixture") is True
        and all(current.get(k) == v for k, v in fixture["catalogue"].items()),
        "Server does not expose this synthetic catalogue",
    )
    query = urllib.parse.urlencode(fixture["catalogue"])
    work = client.request(f"/api/catalogue/works/{WORK}?{query}")
    require(
        work.get("id") == WORK
        and work.get("title") == TITLE
        and work.get("snapshot") == {**fixture["catalogue"], "fixture": True},
        "Server does not expose the selected synthetic work",
    )
    client.csrf = session["csrf"]
    return root, fixture, client, listing


def saved_inputs(root):
    marker = root / "check-result-inputs.json"
    require(marker.is_file() and not marker.is_symlink(), "Run the API check before queue control")
    return json.loads(marker.read_text())


def check(root, base_url, *, trust="configured"):
    root, fixture, client, listing = connect(root, base_url)
    key = lambda name: uuid.uuid5(uuid.UUID(fixture["run_id"]), name)
    native = client.wait(
        client.request(
            "/api/direct-library/books/1/inspect",
            {"inventory": listing["inventory"]["token"]},
            key=key("native"),
            expected=ACCEPTED,
        )
    )
    require(
        native["source_sha256"] == fixture["source_sha256"],
        "Native capture did not preserve synthetic bytes",
    )
    report = client.request(f"/api/epub-inspections/{native['id']}/report")
    require(report["report"]["structural_check"] == "passed", "Synthetic source failed structure")
    inventory = {name: listing["inventory"][name] for name in ("token", "library_uuid")}
    reconciliation = client.wait(
        client.request(
            "/api/library/reconciliation-jobs",
            {**fixture["catalogue"], "inventory": inventory},
            key=key("reconcile"),
            expected=ACCEPTED,
        )
    )
    saved_key = reconciliation["request_key"]
    saved = client.request(f"/api/library/reconciliations/{saved_key}")
    require(
        saved["inventory_total"] == 2
        and saved["catalogue"] == {**fixture["catalogue"], "fixture": True},
        "Saved reconciliation does not match the fixture",
    )
    listed = client.request(
        "/api/library/reconciliations?" + urllib.parse.urlencode(fixture["catalogue"])
    )
    require(
        any(row["request_key"] == saved_key for row in listed["reports"])
        and all(
            row["catalogue"]["sha256"] == fixture["catalogue"]["sha256"]
            for row in listed["reports"]
        ),
        "Saved reconciliations were not filtered by the selected catalogue pin",
    )
    client.request(
        "/api/library/reconciliations?version=" + fixture["catalogue"]["version"], expected=400
    )
    body = {
        **fixture["catalogue"],
        "catalogue_work_id": WORK,
        "source_sha256": native["source_sha256"],
        "report_sha256": report["report_sha256"],
        "reconciliation": saved_key,
    }
    route = f"/api/epub-inspections/{native['id']}/checks"
    # An uncertain POST is recoverable only once accepted; an unsent key is honestly absent.
    client.request(f"{route}?request_key={key('never-sent')}", expected=404)
    ordinary = client.wait(
        client.request(route, body, key=key("unselected-reference"), expected=ACCEPTED)
    )
    unpinned = ordinary["result"]["reference_authentication"]
    require(
        unpinned["status"] == "not_requested"
        and unpinned["reason_codes"] == ["reference_not_pinned"]
        and unpinned["reference_id"] is None
        and ordinary["reference"] is None,
        "Unselected reference acquired authentication",
    )
    # A selection change under the same key is refused rather than silently replaced.
    client.request(
        route,
        {**body, "reference": fixture["reference"]},
        key=key("unselected-reference"),
        expected=409,
    )
    client.request(
        route,
        {**body, "reference": {**fixture["reference"], "authority_id": AUTHORITY}},
        key=key("malformed-reference"),
        expected=400,
    )
    require(
        {"content_identity_unconfirmed", "semantic_duplicates_unconfirmed", "writer_not_authorized"}
        <= set(ordinary["result"]["blockers"]),
        "Ordinary assessment lost required holds",
    )
    require(
        ordinary["result"]["duplicates"]["exact_bytes"]["count"] == 1
        and ordinary["result"]["duplicates"]["exact_bytes"]["books"][0]["book_id"] == "2",
        "The synthetic second library record was not reported as an exact copy",
    )
    discovery = client.request(
        "/api/content-trust/references?"
        + urllib.parse.urlencode({**fixture["catalogue"], "work": WORK})
    )
    reference_job = None
    if trust == "configured":
        require(
            discovery["status"] == "available"
            and discovery["registry_sha256"] == fixture["reference"]["registry_sha256"],
            "Synthetic curated references are unavailable",
        )
        require(
            any(
                row["reference_id"] == REFERENCE
                and row["manifest_sha256"] == fixture["reference"]["manifest_sha256"]
                for row in discovery["references"]
            ),
            "Synthetic reference was not advertised",
        )
        reference_job = client.wait(
            client.request(
                route,
                {**body, "reference": fixture["reference"]},
                key=key("reference-match"),
                expected=ACCEPTED,
            )
        )
        auth = reference_job["result"]["reference_authentication"]
        require(
            auth["status"] == "authenticated_reference_match"
            and auth["reference_sha256"] == native["source_sha256"]
            and auth["report_sha256"] == report["report_sha256"],
            "Exact synthetic reference did not authenticate",
        )
        require(
            "work_identity" in auth["claims"]
            and auth["authority_id"] == AUTHORITY
            and auth["registry_sha256"] == fixture["reference"]["registry_sha256"]
            and auth["manifest_sha256"] == fixture["reference"]["manifest_sha256"]
            and auth["catalogue"] == {**fixture["catalogue"], "work_id": WORK}
            and "content_identity_unconfirmed" not in reference_job["result"]["blockers"],
            "Authenticated work claim was not bound",
        )
        # Mixed or unknown pins never fall back to the advertised reference.
        digest = "0" * 64
        mixed = {
            "registry": ({"registry_sha256": digest}, "registry_pin_mismatch"),
            "manifest": ({"manifest_sha256": digest}, "manifest_pin_mismatch"),
            "unknown": ({"reference_id": "synthetic.unknown"}, "reference_not_registered"),
        }
        for name, (change, code) in mixed.items():
            refused = client.wait(
                client.request(
                    route,
                    {**body, "reference": {**fixture["reference"], **change}},
                    key=key("mixed-" + name),
                    expected=ACCEPTED,
                )
            )
            outcome = refused["result"]["reference_authentication"]
            require(
                outcome["status"] == "unconfirmed"
                and code in outcome["reason_codes"]
                and outcome["claims"] == []
                and "content_identity_unconfirmed" in refused["result"]["blockers"],
                "A mixed or unknown reference pin acquired authentication",
            )
    else:
        require(
            trust == "not_configured"
            and discovery["status"] == "not_configured"
            and discovery["reason_codes"] == ["trust_not_configured"]
            and discovery["registry_sha256"] is None
            and discovery["references"] == [],
            "Expected an explicitly unconfigured trust store",
        )
        # A remembered pin remains an honest unknown when trust is not configured.
        reference_job = client.wait(
            client.request(
                route,
                {**body, "reference": fixture["reference"]},
                key=key("unconfigured-pin"),
                expected=ACCEPTED,
            )
        )
        outcome = reference_job["result"]["reference_authentication"]
        require(
            outcome["status"] == "unconfirmed"
            and outcome["reason_codes"] == ["trust_not_configured"]
            and "content_identity_unconfirmed" in reference_job["result"]["blockers"],
            "An unconfigured trust store acquired authentication",
        )
    changed = client.wait(
        client.request(
            "/api/epub-inspections",
            (root / "inputs/changed.epub").read_bytes(),
            key=key("changed"),
            upload=True,
            expected=ACCEPTED,
        )
    )
    changed_report = client.request(f"/api/epub-inspections/{changed['id']}/report")
    changed_body = {
        **body,
        "source_sha256": changed["source_sha256"],
        "report_sha256": changed_report["report_sha256"],
        "comparison_inspections": [
            {
                "job_id": native["id"],
                "source_sha256": native["source_sha256"],
                "report_sha256": report["report_sha256"],
            }
        ],
    }
    if trust == "configured":
        changed_body["reference"] = fixture["reference"]
    changed_route = f"/api/epub-inspections/{changed['id']}/checks"
    changed_job = client.wait(
        client.request(
            changed_route, changed_body, key=key("changed-assessment-" + trust), expected=ACCEPTED
        )
    )
    result = changed_job["result"]
    overlap = result["duplicates"]["content"]["comparisons"][0]
    require(
        overlap["document_text_overlap"]["matched_documents"] == 1
        and overlap["resource_overlap"]["matched_documents"] == 0
        and overlap["text_relation"] == "different",
        "Changed markup did not expose the expected document-text lead",
    )
    require(
        result["duplicates"]["other_formats"]["count"] == 1
        and result["duplicates"]["content"]["possible_count"] == 1,
        "Format and duplicate lead counts do not match the fixture",
    )
    if trust == "configured":
        require(
            result["reference_authentication"]["status"] == "different_bytes",
            "Changed bytes acquired exact-reference authentication",
        )
    for job in (ordinary, reference_job, changed_job):
        if job is not None:
            require(
                job["result"]["ready"] is False and job["result"]["correction_admission"] == "held",
                "Assessment admitted a writer",
            )
            require(
                {"semantic_duplicates_unconfirmed", "writer_not_authorized"}
                <= set(job["result"]["blockers"]),
                "Assessment lost semantic or writer holds",
            )
    replay = client.request(
        changed_route, changed_body, key=key("changed-assessment-" + trust), expected=ACCEPTED
    )
    recovered = client.request(
        changed_route + "?request_key=" + str(key("changed-assessment-" + trust))
    )
    require(
        replay["id"] == recovered["id"] == changed_job["id"] and recovered["result"] == result,
        "Idempotent recovery did not retain the exact saved assessment",
    )
    scopes = {route: native["id"], changed_route: changed["id"]}
    for path in (route, changed_route, "/api/library/reconciliation-jobs"):
        first, off_page = client.request(path + "?page=1"), client.request(path + "?page=10000")
        require(
            first["jobs"]
            and off_page["jobs"] == []
            and off_page["total"] == first["total"]
            and first["page_size"] == 24
            and all("result" not in row and "result_summary" in row for row in first["jobs"]),
            "Scoped paged history failed",
        )
        if path in scopes:
            require(
                all(row["source_job_id"] == scopes[path] for row in first["jobs"]),
                "Source history included another inspection's checks",
            )
        for query in ("", "?page=1&page=2", "?page=1&request_key=" + str(key("never-sent"))):
            client.request(path + query, expected=400)
    summaries = {
        row["id"]: row["result_summary"] for row in client.request(route + "?page=1")["jobs"]
    }
    require(
        summaries[ordinary["id"]]["reference_authentication"] == "not_requested"
        and summaries[ordinary["id"]]["exact_bytes"]
        == ordinary["result"]["duplicates"]["exact_bytes"]["status"],
        "History summary does not match the saved assessment",
    )
    selected = reference_job or ordinary
    preparation = {
        **fixture["catalogue"],
        "work": WORK,
        "source_sha256": native["source_sha256"],
        "report_sha256": report["report_sha256"],
    }
    prepare_route = f"/api/epub-inspections/{native['id']}/preparation?"
    prepared = client.request(
        prepare_route + urllib.parse.urlencode({**preparation, "assessment": selected["id"]})
    )
    require(
        prepared["reference_authentication"] == selected["result"]["reference_authentication"]
        and prepared["ready"] is False,
        "Preparation did not preserve historical authentication",
    )
    # A stale selection (another source's assessment) is refused, never substituted.
    client.request(
        prepare_route + urllib.parse.urlencode({**preparation, "assessment": changed_job["id"]}),
        expected=409,
    )
    observed = client.request(
        f"/api/epub-inspections/{native['id']}/source-check",
        {"source_sha256": native["source_sha256"], "report_sha256": report["report_sha256"]},
    )
    require(observed["status"] == "same_bytes", "Native source bytes changed during acceptance")
    require(
        source_hashes(root) == fixture["hashes"],
        "Acceptance changed synthetic original source files",
    )
    receipt = {
        "schema": SCHEMA,
        "status": "passed",
        "trust": trust,
        "native_job": native["id"],
        "changed_source_job": changed["id"],
        "reconciliation_key": saved_key,
        "assessment_job": selected["id"],
        "changed_job": changed_job["id"],
        "source_sha256": native["source_sha256"],
        "originals_unchanged": True,
        "writer_admitted": False,
        "limits": [
            "Synthetic API and independent-worker proof only",
            "Browser, cancellation races and real-device acceptance are separate checks",
        ],
    }
    (root / f"check-result-{trust}.json").write_bytes(encoded(receipt))
    (root / "check-result-inputs.json").write_bytes(encoded({"route": route, "body": body}))
    return receipt


def queue_start(root, base_url, *, idle_seconds=3):
    """With the fixture's worker stopped, prove queueing, single-active and cancellation."""
    root, _fixture, client, _listing = connect(root, base_url)
    inputs = saved_inputs(root)
    route, body = inputs["route"], inputs["body"]
    run = uuid.uuid4()
    first, second = uuid.uuid5(run, "cancelled"), uuid.uuid5(run, "after-cancel")
    queued = client.request(route, body, key=first, expected=202)
    require(queued["state"] == "queued", "A new check was not queued")
    time.sleep(idle_seconds)
    observed = client.request(f"{route}?request_key={first}")
    require(
        observed["id"] == queued["id"] and observed["state"] == "queued",
        "A worker is attached; stop only this fixture's worker before queue control",
    )
    # The same intent under a new key cannot run twice while the first is active.
    client.request(route, body, key=second, expected=409)
    cancelled = client.request(f"/api/jobs/{queued['id']}", {})
    require(
        cancelled["state"] == "cancelled" and cancelled["attempts"] == 0,
        "Cancellation did not stop the queued check before any attempt",
    )
    replay = client.request(route, body, key=first, expected=ACCEPTED)
    require(
        replay["id"] == queued["id"] and replay["state"] == "cancelled",
        "Replaying a cancelled request queued unintended work",
    )
    pending = client.request(route, body, key=second, expected=202)
    require(pending["state"] == "queued", "A fresh key after cancellation was not queued")
    state = {"cancelled": queued["id"], "first": str(first), "second": str(second)}
    state["pending"] = pending["id"]
    (root / "queue-pending.json").write_bytes(encoded(state))
    return state


def queue_finish(root, base_url):
    """After restarting only this fixture's worker, the fresh request runs exactly once."""
    root, fixture, client, _listing = connect(root, base_url)
    marker = root / "queue-pending.json"
    require(marker.is_file() and not marker.is_symlink(), "Run queue-start first")
    state = json.loads(marker.read_text())
    route = saved_inputs(root)["route"]
    done = client.wait(client.request(f"/api/jobs/{state['pending']}"))
    cancelled = client.request(f"{route}?request_key={state['first']}")
    require(
        done["attempts"] == 1
        and cancelled["id"] == state["cancelled"]
        and cancelled["state"] == "cancelled"
        and cancelled["attempts"] == 0
        and cancelled["result"] == {},
        "Cancelled work ran after the worker restarted",
    )
    recovered = client.request(f"{route}?request_key={state['second']}")
    require(
        recovered["id"] == done["id"] and recovered["result"] == done["result"],
        "Recovery did not return the saved post-cancellation result",
    )
    require(source_hashes(root) == fixture["hashes"], "Queue control changed synthetic originals")
    receipt = {
        "schema": SCHEMA,
        "status": "passed",
        "queue": {"cancelled_attempts": 0, "fresh_attempts": 1},
        "cancelled_job": state["cancelled"],
        "completed_job": done["id"],
        "originals_unchanged": True,
    }
    (root / "check-result-queue.json").write_bytes(encoded(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "check", "queue-start", "queue-finish"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--trust", choices=("configured", "not_configured"), default="configured")
    args = parser.parse_args()
    try:
        if args.mode == "prepare":
            require(args.base_url is None, "Prepare does not contact a server")
            prepare(args.root)
            print(
                "PREPARED: synthetic fixture and private environment files; no runtime check performed"
            )
            return
        require(args.base_url is not None, "Check needs a loopback acceptance URL")
        if args.mode == "check":
            check(args.root, args.base_url, trust=args.trust)
            print(
                "PASS: synthetic assessment API, independent worker, curated references and preserved originals"
            )
        elif args.mode == "queue-start":
            queue_start(args.root, args.base_url)
            print(
                "QUEUED: cancellation proven; restart only this fixture's worker, then queue-finish"
            )
        else:
            queue_finish(args.root, args.base_url)
            print("PASS: cancelled work stayed unexecuted and the fresh request ran once")
    except ProofError as error:
        # Proof messages are fixed strings without paths, endpoints or credentials.
        parser.exit(1, f"Assessment acceptance failed: {error}\n")
    except OSError, ValueError, KeyError, TypeError:
        parser.exit(
            1, "Assessment acceptance failed; inspect the private proof state and service logs.\n"
        )


if __name__ == "__main__":
    main()
