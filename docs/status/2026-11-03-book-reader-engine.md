# Book reader engine, 2026-11-03

[L074](../decisions.md#l074-foliate-js-reader-page-with-its-own-policy) replaces the
first reader's renderer with vendored foliate-js on its own `/read/<id>` page:
paginated turns by default with two-page spreads on wide screens, scrolled mode as
an option, tap thirds, swipe, keys and visible page buttons, a Contents side panel
on wide screens and the cover-lit room in every theme. Places keep a CFI and still
open older section places. Frontend tests, backend policy tests and a headless
Chrome check (hostile book, inherited frame policy, links, layout at 1440px and
390px in dark and light themes) pass with fixture books. Firefox, Safari, physical
devices, screen readers and the live library are not yet exercised. Search,
highlights, read-aloud and fixed-layout books are deferred.
