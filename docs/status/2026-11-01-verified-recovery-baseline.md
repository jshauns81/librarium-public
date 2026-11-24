# Verified recovery baseline, 2026-11-01

[L067](../decisions.md#l067-verified-recovery-baselines-before-delivery) requires a
verified offline baseline for new content-server delivery and Undo. It binds
session, library, exact journal history and retained artifacts, with an fsynced
operation manifest checked again before replacement. Missing or changed evidence
refuses; historical reconciliation remains observation-only without a current
baseline. The [contract](../delivery-recovery.md) and [regression evidence](../delivery-recovery.tdd.md)
separate captured-byte integrity from operator coordination, actual restore
usability and physical durability. No production service or real library changes.
