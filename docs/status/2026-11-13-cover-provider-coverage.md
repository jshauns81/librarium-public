# Web cover provider coverage

The source role now accepts an optional Google Books API key only in its protected
role environment and Google child. Unkeyed behavior remains available; keyed calls
refuse redirects. Missing Hardcover access is `not_configured`, distinct from
rejected or unavailable access, and has no source retry action.

Archived Lexicanum prioritizes setting/series terms in the title, bounds pacing,
requests and retry waits by the wiki budget, and retains covers found before a
later timeout. `partial` coverage reaches the worker and picker without entering
the complete cache or implying absence. Open Library candidates can use edition
cover IDs, cover edition OLIDs or valid ISBNs when work cover IDs are absent.

Web choices sort by score. Weak or unknown scores show Possible match beside the
choice and selected cover while preserving explicit visual confirmation and
existing admission. Source-role operational records contain only source, state,
count and duration, including cache hits and failures.

Reuse: retained Library Finish provider parsing, scoring, transport and image
admission remain the implementation owners. The existing BL Catalog snapshot
cover path remains available; the provider evidence and retained changeover
contracts supply no alternative runtime implementation of these six gaps. No new
dependency, provider, live search, release, installed service or operator
configuration is introduced.

Verification results are recorded with the pull request. The local image proof is
synthetic and does not establish live provider availability or a configured key.
The next separately authorized acceptance can exercise these changes after release;
this PR leaves installation and operator access setup outside its scope.
