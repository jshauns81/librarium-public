# Product brief

## Ambition

Librarium is one application for the maintainer's Warhammer and Black Library books,
bringing bibliographic knowledge, library management and book preparation into
one continuous experience.
It should feel sophisticated, visually rich and inviting to spend time in:
books, artwork, titles, authors and series give the experience its purpose.
Generous, readable composition is the target. Maximizing visible database rows
is not a product goal. Powerful engineering remains available when the task
calls for it.

The assistants must research and recommend the architecture, explain consequential
tradeoffs, and challenge assumptions rather than defer technical choices back to
The maintainer. Browsing should feel as considered on a phone as on a desktop.

The maintainer's standing direction on 2026-10-25 is to continue toward a complete product
autonomously, asking when a consequential constraint is missing. The site should
have character: he welcomes animation and color changes and explicitly rejects a
boring result. His supplied archivist emblem is the identity anchor. Motion must
still respect reduced-motion preferences and preserve dependable task behavior.

This brief defines the product target. L007 authorizes local implementation;
neither existing application is retired, and illustrated features remain subject
to the real product needs. See [status](docs/status.md) and [decisions](docs/decisions.md).

## One application and one book journey

Organize the product around a book and the reader's task. Browsing an existing
book or adding an incoming file leads into its identity, condition, checks
and history without requiring the reader to switch between tools.
Catalogue knowledge belongs beside the book and its source evidence. Background
jobs, explicit choices and recovery retain that same context through reloads and
navigation.

Reuse the retained engines internally. Their original project names identify
engineering provenance, not product modes, separate workbenches or applications
embedded inside Librarium. Useful Library, search and history views can remain;
their actions must form a coherent workflow with consistent language and state.
Combining menus or renaming screens alone does not satisfy this requirement.

Preserve original bytes, evidence boundaries, ambiguity, explicit approval and
writer safety throughout the unified journey. Integration must make these
understandable without making the reader reconstruct the workflow from job IDs,
source applications or disconnected technical pages.

Legacy-client compatibility supports migration and eventual replacement. It
does not lead the product experience or substitute for native workflow integration.
Retiring or activating services retains its separate approval boundary.

## Journeys to assess

| Journey | Desired experience | Evidence needed |
|---|---|---|
| Explore a collection | Search, browse, filter, and return to the same place without losing state | Representative collection sizes, keyboard/touch navigation, query behavior |
| Understand a work | See editions, series, identifiers, provenance, and uncertainty clearly | Existing BLC contracts and identity/evidence model |
| Check a book | Inspect a candidate, compare evidence, and see exactly what is wrong | Existing Library Finish workflow and preservation guarantees |
| Follow ongoing work | Check progress, navigate, and act while checks run | Slow/failing jobs, retries, reconnects, stale/out-of-order responses |
| Report a problem | Know which check found what, and that the book itself is never rewritten | Inspection, EPUBCheck and assessment reports; the library is cleaned at the source |
| Continue on mobile | Resume the same task and understand current state | Real narrow-screen journeys and accessible touch controls |

## Required qualities

- A control acknowledges the user's intent promptly and completes the intended
  action or explains a failure. Silent dropped clicks are defects.
- Long-running work survives browser closure and assistant disconnects on the
  eventual execution host. It does not occupy the interactive request path.
- The interface preserves selection, focus, scroll, and unsaved input during
  updates. Stale responses cannot silently replace newer user intent.
- Visible claims have evidence: provenance, validation, repair outcomes, and
  confidence cannot be fabricated from placeholders or generated screenshots.
- Original content is preserved. Existing library writers and the catalogue's
  consumer contracts remain explicit boundaries throughout evaluation.
- Accessibility, responsive layout, loading/empty/error states, observability,
  recovery, and upgrades are part of the product, not final polish.
- Browsing, understanding a book and following a series are first-class pleasures,
  alongside inspection and repair. Advanced search, matching, evidence, history,
  reviews, integrations and diagnostics retain their capabilities and clear paths
  from the relevant book or task. [UX standards](docs/ux-standards.md) owns
  hierarchy, truthful status and disclosure; visual simplification must preserve
  useful information and actions.
- Two rooms at launch, chosen by the owner on 2026-11-03: Dark (a candlelit
  scriptorium, the first-visit default) and Light (vellum and lapis), plus
  following the device. Each is lit by the open book's cover. The supplied
  emblem must recolor with the site through actual vector artwork.

## Questions the assessment must answer

Identify the real domain boundaries and source of truth for each kind of data;
decide which existing engines should be retained and how the UI should consume
them. Define the useful first release without expanding into every possible
format, automation, or reading feature. Separate the experience of a combined
product from the physical placement of all services in one repository.

## Future: accounts and personal collections

Plan for invited users to sign in through a branded experience and use their own
collections, preferences and history within the existing reading-room design.
Content may span genres beyond Warhammer; specialized reference catalogues must
be optional for general browsing. The [future account plan](docs/design/accounts-and-collections.md)
defines ownership, sharing, identity and migration questions. This is planned
scope, not current account isolation or an expansion of the active delivery work.

The concepts in [inspiration](images/inspiration/README.md), especially
`librarium-03-reading-room.png`, express the aspiration: a personal literary
space with confident typography, artwork and room to read. Interpret that quality
for collection browsing and engineering workflows. The illustrated reader, book
imagery, chapter text, statistics and quality claims establish no shipping assets,
reader feature, evidence or accepted scope. Cover integration still requires the
read contract defined by [UX standards](docs/ux-standards.md).
