# Delivery recovery evidence

Date: 2026-11-01. Journeys derive from the accepted supervised-delivery sequence
and [L067](decisions.md#l067-verified-recovery-baselines-before-delivery).
Reuse LF backup readiness, existing immutable artifact readers, the broker journal
and PostgreSQL dump/restore acceptance. No backup daemon, new dependency or second
book writer is introduced.

## Failing-first evidence

The initial 19 cases reproduced missing recovery admission and exercised the new
offline baseline contract. Review then reproduced operation-manifest tampering,
unsynced identical-file retries, expiry during final recovery reads, nested backup
mutation, divergent histories with equal journal cursors, offline command retries
after failed fsync and mutation between hashing and stat pinning. Corrections
retain refusal/uncertainty boundaries and have executable regressions. A final
malformed-manifest review reproduction adds redacted CLI failures instead of an
uncaught traceback.

`uv run pytest -W error backend/tests/test_delivery_recovery.py -q` passes 51 cases.

| Guarantee | Regression | Result |
|---|---|---|
| New content-server writes require a verified baseline with no environment bypass | `test_operational_writer_refuses_without_a_verified_baseline`, `test_content_server_configuration_has_no_optional_recovery_bypass` | PASS |
| Delivery and Undo persist exact recovery evidence before send; historical replay needs no backup | `test_verified_baseline_binds_recovery_manifest_before_send_and_replay_needs_no_backup` | PASS |
| Missing, altered or incorrectly bound backup evidence sends nothing | `test_invalid_baseline_refuses_before_intent` | PASS |
| Preflight mutation stops sends and post-intent uncertainty stays held | `test_changed_backup_during_preflight_never_sends_and_post_intent_keeps_hold` | PASS |
| Exact historical journal bytes matter even when counts and sequences match | `test_equal_counts_with_different_historical_journal_bytes_refuse` | PASS |
| Existing manifests/receipts can be durably retried after fsync failure without replacement | `test_offline_caller_can_retry_after_fsync_failure_without_replacing_evidence` | PASS |
| Saved operation evidence is checked again before send | `test_recovery_package_is_rechecked_before_send` | PASS |
| Nested backup changes are caught without hashing every book at runtime | `test_mutated_nested_baseline_evidence_refuses_even_when_not_selected`, `test_runtime_does_not_rehash_the_whole_library` | PASS |
| Review/session authority is checked after recovery reads | `test_authority_expiring_during_recovery_read_is_rechecked` | PASS |
| Offline tools reject aliases, unsupported entries, incomplete evidence and malformed manifests without leaking configured paths | `test_offline_verification_refuses_incomplete_or_aliased_components`, `test_cli_capture_redacts_malformed_existing_manifest` | PASS |

Focused recovery coverage was 88% before the final malformed-input cases. Full
delivery-group coverage and native/HTTP evidence are recorded separately; this
focused figure does not imply whole-application coverage.

The final delivery group passes 345 warning-strict tests at 89% combined
broker/writer/recovery coverage (950 statements, 100 missed). Nine pinned Calibre
9.17.0 synthetic native cases pass in an isolated network namespace. Mypy checks
96 files; Ruff, Django/schema and preserved-workspace checks pass.

## Integrated proof and limits

*Retired 2026-11-22 (L091): the integrated proof below needed the removed web, dispatcher and correction roles; `tests/test_delivery_http_proof.py` and its script are gone. The writer core's native, kill and content-server proofs remain.*

`tests/test_delivery_http_proof.py` drove the separate web, inspection worker,
dispatcher, writer and authenticated pinned Calibre server. Its fixture stops
only its own processes, creates real PostgreSQL dumps, verifies independent
baseline generations and mounts the selected baseline read-only for the writer.
It exercises delivery, Undo, cancelled requests, lost replies/restarts and a
coordinated restore into separate state. Writer readiness is checked after each
fixture baseline restart before a new supervised confirmation is issued.
Preparations are refreshed after writer restarts, preserving the existing boot
identity fence. Request-key replays do not create another baseline or restart
roles; they retain their exact original request binding.
The outer test allows 900 seconds for the repeated stopped-role captures and
verified-runtime restarts. This rehearsal budget changes no production deadline.

Full hashing proves the captured bytes, not operator coordination or PostgreSQL
dump usability. Runtime stat pins detect filesystem mutations; selected artifacts
are rehashed, but unrelated media are not continuously checked for silent bit rot.
The actual restore rehearsal supplies separate usability evidence. Physical
power loss, real storage and library trials remain outside these generated
fixtures. No hold reset, automatic resend, retention cleanup or live activation
is introduced.
