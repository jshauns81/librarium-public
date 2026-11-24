# Storage ownership roadmap, 2026-11-03

[L076](../decisions.md#l076-storage-ownership-is-settled-before-the-first-production-release)
is approved. It keeps Calibre as the catalogue
of record with the content server as its only writer, makes PostgreSQL the record
for everything Librarium owns, fixes the data flow as one-way Calibre to Postgres,
and makes the read model the only listing path before production activation.
The intended sequence is parity verification, a complete library-aware model, removal of the fallback, and separately approved writer testing on an isolated library.
