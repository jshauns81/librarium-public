# Trusted operator identity, 2026-11-13

The beta's principal-protected APIs previously had no authenticated WSGI identity
handoff. A default-off outer WSGI adapter now accepts `X-Librarium-Operator` only
from the exact literal peers in web's `LIBRARIUM_OPERATOR_PROXY_IPS`. It consumes
the header and discards both ambient `REMOTE_USER` and HTTP `Remote-User` before
setting a validated principal. The registry validator restricts the new setting
to web, rejects other operator settings and refuses broad or malformed peers.

[L088](../decisions.md#l088-default-off-trusted-operator-identity) records the beta
mTLS-to-operator decision; [packaging](../packaging.md#optional-trusted-operator-identity-for-the-beta)
owns the exact environment and nginx directive shapes. Successfully verified
certificates map to the fixed name `operator`; certificate DNs are not principals.
Existing cover/search actor checks, quotas, delivery supervision, CSRF and writer
approval boundaries stay in force. Production proxy/authentication topology
remains unapproved.

Failing-first tests cover trusted and untrusted peers, disabled forwarding,
spoofed/ambient identity, malformed names and configuration, and web-only registry
admission. Pinned Gunicorn parser tests exercise duplicate headers, underscore
aliases and non-ASCII input. Consumer tests prove cover review, search, delivery
approval and workspace gates share the same principal without executing a writer.
The focused suite passes 217 checks with warnings treated as errors and 100%
statement coverage of the identity adapter. The broader affected suite passes
436 checks. Type checks over 124 source files, backend lint, Django system and
migration-drift checks, workspace/archive integrity, documentation links and
private-denylist checks pass. Hosted checks and independent review remain PR
acceptance gates; local tests do not prove the installed ingress topology.

Reuse: BLC's API, LF's HTTP handlers, plans and changeover list, the existing
Librarium principal/supervised-delivery boundary, pinned Gunicorn and nginx. The
new adapter supplies only the missing peer-bound WSGI handoff, using the standard
library. No beta/ingress configuration, installed application, library content
or release changed. No user testing is needed until separately authorized beta
activation; that follow-up must validate mTLS admission, identity spoof refusal
and operator API access against the installed topology. This PR is not merged.
