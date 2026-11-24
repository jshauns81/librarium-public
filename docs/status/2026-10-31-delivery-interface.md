# Delivery interface, 2026-10-31

A validated held copy now carries a Library delivery panel built on the frozen
L055 HTTP contract. It prepares an explicit review, then shows the selected copy and
its validation, the native book, unchanged library title/authors versus validated
internal EPUB changes, the retained original, per-change hold classification and
the duplicate notes that must be acknowledged for that one request. Delivery needs
an explicit confirmation. Progress, outcome and Undo states come only from jobs,
projections and immutable receipts; the record keeps “validated; held for
delivery” until an independently read-back receipt verifies the replacement.

Every request retains its key until the service confirms it, so a lost reply is
recovered by the same key and never becomes a second intent. Check outcome and
Undo appear only when the delivery record allows them; Undo restates its guard and
needs its own confirmation. Stop before send reports “Cancelled before delivery;
library unchanged” only from the recorded no-send receipt, and a stop after send
remains an outcome check. Offline status, read failures and unknown codes stay
separate from the recorded library state. Reviews, progress labels and terminal
announcements no longer describe delivery jobs as completed inspections.

Frontend verification passes 802 tests at 91.8% line coverage, plus types,
formatting, production build and dependency audit. A private synthetic browser proof
against the delivery backend base used separate web, inspection, dispatcher and writer
processes, PostgreSQL, the pinned runtime and a generated library. It covered the
contents-only review, a catalogue identity hold, keyboard-only delivery with reload
and history, a dropped reply, writer death with Check outcome, external drift,
guarded Undo, an Undo conflict and stops before and after send. Rendered samples at
desktop, 390px, 320px and doubled text across every theme and System light/dark had
no accessibility-rule violations, overflow, unlabelled controls or small touch targets.
The decoder also accepts the security-review receipt diagnostics in unit tests; the
revised backend has not been exercised through the browser in this proof.
