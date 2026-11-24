# Catalogue tool-health dashboard, 2026-11-04

The Catalogue navigation item now opens a tool-health dashboard; the existing
book browser is the Books tab and operations keep their tab, so a browsing place
survives switching. One read-only endpoint, `/api/catalogue/health`, adapts BL
Catalog's status view (`catalogue()` and `changes()`) to what Librarium can read:
the served snapshot, the previous kept snapshot, the evidence and cover tables a
snapshot carries, reference-import state and Librarium's own jobs. BL Catalog's
live harvester status, cycle log, cover inbox, pause switch and scan/cover/upscale
controls are not reachable from Librarium, and none of the three clients reports
health; the page names each as unavailable with its reason. Backend and component
tests pass with fixtures. After synchronizing with main, 263 catalogue backend
tests and 155 focused frontend tests pass, along with types, lint, build and the
owned documentation link audit. Rendered checks use a real read-only catalogue
snapshot and admitted local cover bytes in both rooms at 1440px and 390px.
The local operations view uses an unconnected library directory; no live library
access or deployment is exercised. Captures and operational observations stay
in private context. Main's CI workflows and test changes are preserved.
