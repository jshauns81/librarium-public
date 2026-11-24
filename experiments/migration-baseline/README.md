# Preserved migration baseline

Status: **paused, unapproved experiment**. This is not the active Librarium app.

The original uncommitted scaffold was moved here byte-for-byte on 2026-10-24.
[preservation-manifest.json](preservation-manifest.json) records every original
source/configuration path, size, and SHA-256. No original source was deleted or
rewritten. The Python/Django pins and lockfile describe that earlier attempt;
they are not accepted product choices.

It contains an early committed-source capture helper, small identity helper,
read-only Django views, template, and fixture tests. No real upstream snapshot
capture, finished CLI, parity evaluation, CI, or full migration viability proof
has been delivered. References in the old source to missing architecture docs
are historical; the active [assessment brief](../../docs/architecture.md) owns
the current research direction.
