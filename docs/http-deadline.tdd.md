# Content-server HTTP deadline evidence

Date: 2026-11-01. Scope: the existing L060 Calibre transport. Journeys were
derived from the confirmed gap: the old timer began after `opener.open`, leaving
authentication and response headers outside its budget.

Reuse: retain the LF added-formats transport, existing urllib authentication
handlers, broker uncertainty/no-resend rules and bounded JSON/MessagePack reads.
LF and BL Catalog provide no replacement for this urllib deadline boundary.
Use standard-library connection/handler extensions; no new dependency or writer.

## RED and GREEN

`uv run pytest -W error backend/tests/test_delivery_http_deadline.py -q`
failed all seven initial regressions against the old implementation. Trickled
status/headers exceeded the short test budget; a delayed probe, response body,
aggregate authentication sequence and complete JSON prefix could still succeed.
The same seven cases passed after implementation. Three additional regressions
cover address-attempt budgeting, expiry during connect and a stalled TLS handshake.
Independent review reproduced the address/send guard defects before correction.
A later failing-first case covers a trickling anonymous 200 response: deadline
expiry remains a transport failure instead of an open-server configuration refusal.

| Guarantee | Evidence | Result |
|---|---|---|
| Anonymous probe, initial status/header reads, authenticated headers and body share the deadline | `test_absolute_deadline_interrupts_every_http_stage`, six cases | PASS |
| Probe, Digest challenge and retry do not reset the budget | `test_probe_challenge_and_retry_share_one_deadline` | PASS |
| Timer-induced EOF cannot accept a JSON prefix; a following request succeeds after cleanup | `test_timeout_eof_cannot_accept_a_complete_json_prefix_or_affect_the_next_request` | PASS |
| Resolved address attempts use only the remaining budget | `test_connect_attempts_share_the_remaining_budget` | PASS |
| Expiry during connect prevents sending request bytes | `test_expiry_during_connect_cannot_send_request_bytes` | PASS |
| A stalled TLS handshake refuses within the request budget | `test_deadline_bounds_a_stalled_tls_handshake` | PASS |

The short test budget is 250 ms for real peers, with a 650 ms scheduling allowance.
Controlled-clock tests cover exhausted address budgets and post-connect refusal
without depending on watchdog scheduling. Production keeps a fixed 45-second
deadline and maximum 15-second socket waits. Successful requests, authentication
restrictions, response-size limits and binary export remain covered by the
delivery/native suites. Hosted-image acceptance remains separate.

## Limits

The system resolver is synchronous and cannot be interrupted by this watchdog;
an overdue DNS result refuses before connecting or sending. Tests use synthetic
peers and generated books. They grant no deployment, library-write or recovery
activation authority.
