-- bl-catalog schema (spec 4.1 evidence, 4.2 resolved). Idempotent: connect() runs it on
-- every non-read-only open.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 4.1 Evidence (append-only) ------------------------------------------------

CREATE TABLE IF NOT EXISTS source (
    name         TEXT PRIMARY KEY,
    origin_group TEXT NOT NULL,
    priority     INTEGER NOT NULL DEFAULT 0
);

-- source_record.source is deliberately not a foreign key: evidence may be written before the
-- source registry has been synced into `source`.
CREATE TABLE IF NOT EXISTS source_record (
    id           INTEGER PRIMARY KEY,
    source       TEXT NOT NULL,
    native_id    TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    cache_ref    TEXT,
    parsed_json  TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_source_record_content
    ON source_record (source, native_id, content_hash);

CREATE TABLE IF NOT EXISTS claim (
    id         INTEGER PRIMARY KEY,
    record_id  INTEGER NOT NULL REFERENCES source_record (id) ON DELETE CASCADE,
    entity     TEXT NOT NULL CHECK (entity IN ('work', 'edition')),
    field      TEXT NOT NULL,
    value      TEXT NOT NULL,
    value_norm TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_claim_record ON claim (record_id);
CREATE INDEX IF NOT EXISTS ix_claim_lookup ON claim (entity, field, value_norm);

CREATE TABLE IF NOT EXISTS harvest_log (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    query       TEXT NOT NULL,
    status      TEXT NOT NULL,
    http_status INTEGER,
    fetched_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_harvest_log_lookup ON harvest_log (source, query, fetched_at);

-- Downloaded Lexicanum originals. Bytes live in covers/<sha256 prefix>/<sha256> under the
-- data directory; immutable files are shared by snapshots rather than copied into each one.
CREATE TABLE IF NOT EXISTS cover_asset (
    source_url TEXT PRIMARY KEY,
    sha256     TEXT NOT NULL,
    width      INTEGER NOT NULL CHECK (width > 0),
    height     INTEGER NOT NULL CHECK (height > 0),
    media_type TEXT NOT NULL
);

-- Durable idle work, deduplicated by immutable original and pipeline version. Only the
-- harvester writes this queue; a running entry is reclaimed after a worker restart.
CREATE TABLE IF NOT EXISTS cover_upscale_job (
    original_sha256 TEXT NOT NULL,
    pipeline        TEXT NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('pending', 'running', 'done', 'failed')),
    attempts        INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    retry_at        REAL NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL,
    error           TEXT,
    PRIMARY KEY (original_sha256, pipeline)
);
CREATE INDEX IF NOT EXISTS ix_cover_upscale_ready ON cover_upscale_job (state, retry_at);

-- Published derivatives never replace source evidence. Their bytes live in upscaled/
-- with the same content-addressed layout as covers/. Changing an original automatically
-- selects a different derivative; a pipeline upgrade replaces this association on success.
CREATE TABLE IF NOT EXISTS cover_derivative (
    original_sha256 TEXT PRIMARY KEY,
    pipeline        TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    width           INTEGER NOT NULL CHECK (width > 0),
    height          INTEGER NOT NULL CHECK (height > 0),
    media_type      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- 4.2 Resolved (rebuilt by the resolver) -----------------------------------

CREATE TABLE IF NOT EXISTS work (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    sort_title      TEXT,
    type            TEXT,
    setting         TEXT,
    synopsis        TEXT,
    word_count      INTEGER,
    length_class    TEXT,
    first_published TEXT
);

-- One selected Lexicanum cover per work. Keep the metadata in the snapshot, so a scan
-- cannot change the dimensions or file served to readers of an already-published version.
CREATE TABLE IF NOT EXISTS work_cover (
    work_id    TEXT PRIMARY KEY REFERENCES work (id),
    source_url TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    width      INTEGER NOT NULL CHECK (width > 0),
    height     INTEGER NOT NULL CHECK (height > 0),
    media_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edition (
    id              TEXT PRIMARY KEY,
    work_id         TEXT REFERENCES work (id),
    format          TEXT,
    isbn10          TEXT,
    isbn13          TEXT,
    asin            TEXT,
    audible_asin    TEXT,
    publisher       TEXT,
    imprint         TEXT,
    release_date    TEXT,
    region          TEXT,
    pages           INTEGER,
    runtime_minutes INTEGER,
    cover_artist    TEXT,
    cover_url       TEXT,
    price           REAL,
    price_currency  TEXT,
    in_print        INTEGER
);
CREATE INDEX IF NOT EXISTS ix_edition_work ON edition (work_id);
CREATE INDEX IF NOT EXISTS ix_edition_isbn13 ON edition (isbn13);

CREATE TABLE IF NOT EXISTS edition_ident (
    edition_id TEXT NOT NULL REFERENCES edition (id),
    kind       TEXT NOT NULL,
    value      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'disputed')),
    PRIMARY KEY (edition_id, kind, value)
);
CREATE INDEX IF NOT EXISTS ix_edition_ident_lookup ON edition_ident (kind, value);

CREATE TABLE IF NOT EXISTS work_ident (
    work_id TEXT NOT NULL REFERENCES work (id),
    kind    TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (work_id, kind, value)
);
CREATE INDEX IF NOT EXISTS ix_work_ident_lookup ON work_ident (kind, value);

CREATE TABLE IF NOT EXISTS author (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    sort_name TEXT
);

-- Every other spelling the sources credit this author under ("Joshua Reynolds" for "Josh
-- Reynolds"); author.name is the canonical one (resolve/people.py).
CREATE TABLE IF NOT EXISTS author_alias (
    author_id INTEGER NOT NULL REFERENCES author (id),
    name      TEXT NOT NULL,
    PRIMARY KEY (author_id, name)
);

CREATE TABLE IF NOT EXISTS work_author (
    work_id   TEXT NOT NULL REFERENCES work (id),
    author_id INTEGER NOT NULL REFERENCES author (id),
    role      TEXT NOT NULL CHECK (role IN ('author', 'editor', 'narrator', 'cover_artist')),
    PRIMARY KEY (work_id, author_id, role)
);

CREATE TABLE IF NOT EXISTS series (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_series (
    work_id   TEXT NOT NULL REFERENCES work (id),
    series_id INTEGER NOT NULL REFERENCES series (id),
    position  REAL,
    PRIMARY KEY (work_id, series_id)
);

CREATE TABLE IF NOT EXISTS work_alias (
    work_id TEXT NOT NULL REFERENCES work (id),
    title   TEXT NOT NULL,
    PRIMARY KEY (work_id, title)
);

CREATE TABLE IF NOT EXISTS work_tag (
    work_id TEXT NOT NULL REFERENCES work (id),
    kind    TEXT NOT NULL CHECK (kind IN ('faction', 'character', 'planet')),
    value   TEXT NOT NULL,
    PRIMARY KEY (work_id, kind, value)
);

CREATE TABLE IF NOT EXISTS work_contains (
    parent_id TEXT NOT NULL REFERENCES work (id),
    child_id  TEXT NOT NULL REFERENCES work (id),
    position  INTEGER,
    PRIMARY KEY (parent_id, child_id)
);
CREATE INDEX IF NOT EXISTS ix_work_contains_child ON work_contains (child_id);

CREATE TABLE IF NOT EXISTS field_support (
    entity        TEXT NOT NULL CHECK (entity IN ('work', 'edition')),
    entity_id     TEXT NOT NULL,
    field         TEXT NOT NULL,
    value         TEXT,
    score         REAL NOT NULL,
    agree_json    TEXT NOT NULL,
    disagree_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_field_support_entity ON field_support (entity, entity_id, field);

CREATE TABLE IF NOT EXISTS record_link (
    record_id INTEGER NOT NULL REFERENCES source_record (id),
    entity    TEXT NOT NULL CHECK (entity IN ('work', 'edition')),
    entity_id TEXT NOT NULL,
    reason    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_record_link_record ON record_link (record_id);
CREATE INDEX IF NOT EXISTS ix_record_link_entity ON record_link (entity, entity_id);

-- seq is the anchor's age: which of two merging IDs is "older" (spec 4.3). An explicit INTEGER
-- PRIMARY KEY, so VACUUM never renumbers it.
CREATE TABLE IF NOT EXISTS id_anchor (
    seq          INTEGER PRIMARY KEY,
    entity       TEXT NOT NULL CHECK (entity IN ('work', 'edition')),
    id           TEXT NOT NULL,
    anchor_kind  TEXT NOT NULL,
    anchor_value TEXT NOT NULL,
    UNIQUE (entity, anchor_kind, anchor_value)
);
CREATE INDEX IF NOT EXISTS ix_id_anchor_id ON id_anchor (entity, id);

CREATE TABLE IF NOT EXISTS id_alias (
    old_id TEXT PRIMARY KEY,
    new_id TEXT NOT NULL
);
