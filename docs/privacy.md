# Privacy and publication

Personal information and operational agent context stay outside GitHub, including
when an application is intended for public release. Public source approval does
not approve personal names, contact details, private domains, network addresses,
host paths, environment inventories or real-library observations.

## Share agent context privately

Use authenticated shared memory configured in each client. Use the outside-checkout
context directory in [the environment contract](agent-environment.md) for local
handoffs and audit evidence. Preserve ownership, dates, source revision and
uncertainty. Never publish endpoint configuration, private denylists, originals,
transcripts or runtime values. Portable source documentation uses reserved example
names/addresses, repository-relative paths and environment variables.

GitHub repository-owner names needed for source links, image identities and
provenance remain explicit; they are existing public hosting identifiers. That
exception does not permit real names, private contact details or infrastructure.
Third-party author attribution and technical citations must remain accurate.

## Publication scope

This source snapshot has its own history. Publishing source does not publish deployment configuration, release artifacts, or existing installations.

## Check before committing

Run `python3 scripts/check_public_content.py` for generic tracked-content checks.
Run it again with `--denylist /absolute/outside-checkout/private-terms.txt` to
check private names, domains and other operator-specific terms. Alternatively set
`LIBRARIUM_PRIVATE_TERMS_FILE` to that outside-checkout filename in the private
agent environment; `--denylist` overrides it. The private file
contains one term per line, remains outside Git, and diagnostics report categories
and opaque file IDs without printing filenames or matched values. Each ID is
`file-sha256:<SHA-256 of repository-relative UTF-8 path>`; line zero identifies
a path finding. The in-process `scan_repository` result retains exact paths for
private investigation; never publish a mapping that restores private filenames. Use `--staged` to check
index bytes. CI runs generic checks; it cannot infer every person's identity.
Review the diff and binaries manually. These checks do not replace a secrets scan.

Before any public release or visibility change, review all branches/tags and
commit author/committer identities; issue/PR/review text; Actions logs/artifacts;
releases/assets; Pages/wiki; packages and image layers; and generated docs/graphs.
Changing the current files does not remove earlier Git objects or external copies.
A coordinated history rewrite changes commit identities, signatures, active PRs
and release provenance. Review its recovery plan before executing it. GitHub-held
cached and PR references may require support; copies already made by others
cannot be recalled by a repository edit.
