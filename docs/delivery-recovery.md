# Verified delivery recovery baseline

The content-server writer requires a verified backup baseline for each new
supervised delivery or Undo under [L067](decisions.md#l067-verified-recovery-baselines-before-delivery).
This does not create a backup service, restore live state or release an
uncertainty hold.
The [regression evidence](delivery-recovery.tdd.md) records verified cases and limits.

## Prepare and verify offline

First stop the relevant application and library writers and capture one
coordinated generation using established backup tools. Its private root contains
`database.dump`, `library/`, `artifacts/` and `broker/`. The dump must belong to
that same stopped capture; placing unrelated components together cannot establish
their coherence. Checkpoint copied SQLite databases before verification,
preserving originals and earlier generations.

`scripts/delivery_recovery.py capture --root "$BACKUP_ROOT" --session-id "$SESSION_ID"`
inventories this existing backup. It never copies books, schedules backups or
stops services. `verify` with the same arguments independently rehashes the
components and writes a verification receipt. Use a new generation/session for
each action; do not overwrite an earlier capture or receipt.

The manifest binds the generation, library UUID, broker journal identity,
immutable journal cursor and file inventories. Verification checks actual bytes,
library/journal identities, checkpointed SQLite state and unfinished-send evidence.
Links, unsupported entries, changed files and incomplete components refuse.
The receipt binds the exact manifest and verified component identities. Hash
verification proves captured byte integrity; it does not prove successful
PostgreSQL restore, operator coordination, physical durability or the currency
of an older coherent generation.

## Admit one supervised action

Configure the protected backup through `LIBRARIUM_DELIVERY_RECOVERY_DIR` and mount
it read-only for the writer. Keep operational paths outside source control.
After verification, confirm the selected supervised session using the existing
operator confirmation contract. Capture and verification precede confirmation;
refresh any preparation bound to the writer boot identity after restarting it.
existing review and five-minute session limits still apply. No arbitrary daily
backup-age policy or content-server bypass is added.

The gate checks exact library, journal, session and manifest bindings, detects
unrelated immutable journal advancement, and rehashes this action's original,
replacement, validation and evidence artifacts. It does not rehash every book on
each network call. Retained immutable artifacts supply recovery bytes without
another EPUB-copy engine.

Before intent, an exclusively created, fsynced operation manifest binds request,
approval, session, baseline and artifact descriptors beneath the broker's private
recovery directory. Admission and saved operation evidence are checked again
before replacement. Authority is rechecked after these reads. A pre-intent
refusal sends nothing; post-intent failures retain the uncertainty hold. Existing
indefinite retention covers originals, outputs and recovery evidence.

## Reconcile and rehearse

Historical keys, receipts and reconciliation remain available without a current
baseline. They only observe; a new baseline grants neither resend nor hold
release. Undo requires a new supervised action/baseline and exactly the delivered
bytes at the destination.

The isolated HTTP acceptance proof uses generated books, stops its own roles,
creates a real PostgreSQL dump and verifies the copied components for each
supervised action. Its coordinated restore uses a separate database/root,
reopens receipts and exact keys, verifies originals, starts a fresh writer epoch
and checks that no second operation was created. Production backup, rollback
and activation retain their concrete reviewed scope; no real-library restore
or identity-provider change is authorized here.


## Reporting isolated rehearsal evidence

[Operational support](operational-support.md) reports strict retained rehearsal
evidence with separately measured restore duration, capture age and build/policy
bindings. The existing restore assertions still establish the tested synthetic
scope. Reporting freshness and a recorded rehearsal confer no baseline, writer,
supervision, resend, hold-release or Undo authority.
