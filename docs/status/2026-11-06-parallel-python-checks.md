# Parallel Python checks, 2026-11-06

The Python suite defaults to three pytest-xdist workers in `pyproject.toml` so
the required source-quality invocation runs in parallel without changing a
policy-locked workflow. Test collection IDs, WSGI fixture setup and timeout child
PID assertions support independent workers. Both images retry snapshot archive
fetches. The Landlock requirement remains in the separate CI change; this change
does not modify workflows or the kernel-dependent skip policy.
Inspection-worker tests commit their jobs so the heartbeat's separate connection
can renew them even when a slower run crosses the heartbeat interval. The
unsupported-label regression waits for a successful heartbeat before publication.
The shared validation/correction store and inspection API store also commit jobs
for worker connections. Workspace lineage and API-report regressions require a
successful heartbeat before using validation pins or publishing report evidence.
