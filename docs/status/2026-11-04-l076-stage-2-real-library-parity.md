# Read-model parity

Calibre applies SQLite `NOCASE` collation to its title and name sort keys. The read model folds ASCII case to reproduce that order. Test fixtures include lowercase sort keys that would sort differently under binary collation. Compare both ordering and per-book fields before enabling a read model for an installation.
