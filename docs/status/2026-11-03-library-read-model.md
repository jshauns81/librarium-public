# Library read model, 2026-11-03

[L075](../decisions.md#l075-postgres-read-model-of-the-calibre-library) adds step one of
the storage review: a worker-refreshed Postgres read model of the Calibre library
behind `LIBRARIUM_LIBRARY_READ_MODEL` (default `off`). Served listings, search,
recent and series produce JSON identical to the direct reader on the test
fixtures (title, recent, paging, ASCII and non-ASCII search, LIKE metacharacters,
series order) without touching the share. `manage.py library_read_model parity`
proves the copy book by book. Persistent database connections are on.
