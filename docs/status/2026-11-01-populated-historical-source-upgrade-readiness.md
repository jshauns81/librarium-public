# Populated historical-source upgrade readiness, 2026-11-01

[L072](../decisions.md#l072-populated-historical-source-upgrade-rehearsal) addresses
issue #25's routine source/synthetic transition from a pinned sanitized historical
source at schema 0005 through current schema 0010. [The procedure](../populated-upgrade.md)
owns coordinated stopped-role capture, historical evidence reopening, pending-policy
refusal, current work and separate old-generation recovery with an explicit loss
boundary. [Verification](../populated-upgrade.tdd.md) distinguishes actual local
source execution from mandatory affected-image CI. Original-image equivalence and
installed-target state remain unproven. Issue #25's target evidence and issue #26's
authorized activation/human observation remain open; no application is newly installed.
