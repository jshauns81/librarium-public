# Dockhand deployment contract

All addresses, paths and project names below are examples. Actual installations,
source/image pins, recovery evidence and operator-specific routing belong in
[private context](agent-environment.md#private-context-discovery). These instructions
do not prove a deployment exists or authorize activation.

## Registry beta path

For new beta releases use `compose.registry.yaml`, with **Build images on deploy
disabled** and automatic updates/webhooks/schedules off. The build-based setup
below is a separate candidate path; do not alter another installation during setup.

Use a protected named configuration branch or an immutable tag for the Git
selection. The inspected Dockhand checkout uses `git clone --branch`, which
does not accept a raw commit SHA as its branch argument. Verify that the named
ref resolves to the reviewed commit and that an isolated authenticated checkout
succeeds before saving it. Record this configuration pin separately from the
image's original release provenance. A settings-only correction must not invoke
deployment or synchronization, change environment overrides or restart containers.

For native read-only Library browsing, select `compose.registry-library.yaml`
as Dockhand's single Compose entry. Its `include.path` list merges
`compose.registry.yaml` and `compose.library.yaml`; Docker Compose 2.20 or newer
is required ([include contract](https://docs.docker.com/reference/compose-file/include/)).
Set `LIBRARIUM_LIBRARY_HOST_PATH=/srv/example/Books/CalibreLibrary`. Only web receives
the read-only `/library` mount and its LF origin is cleared. Keep the image pinned
to the published release digest; record the deployment configuration revision
separately when it adds only deployment files after the application release.
File inspection and native producer state remain separately configured roles.

For the unified preserved-book workspace, select `compose.registry-workspace.yaml`
after the actual target's file-processing isolation, storage and assessment-input
checks pass. This single entry combines registry, native library, preserved-file,
assessment and runtime-login configuration. Web and worker share private beta
artifacts and the same read-only library/catalogue inputs. It adds no library-writing mount
and no delivery role (the delivery worker was removed). Verify the final resolved configuration against
production using `scripts/registry_config.py`; configuration validation does not
prove kernel support, database grants or an installed digest.

This entry requires `LIBRARIUM_RUNTIME_DB_PASSWORD`, independent of the owner
password and used only for Compose interpolation. It must not appear as that
environment key inside a Django role, where it would override the checked password.
The dependency chain is owner migration, create-only login bootstrap, existing
owner grant provisioner, read-only runtime identity/grant verification, then
web/worker. Failed steps keep both foreground roles stopped. Existing logins are
not rotated; an incorrect password, elevated attributes, memberships or owned
objects refuse admission. Owner credentials stay in the bootstrap roles.

The two bootstrap scripts are read-only configuration mounts from the selected
Git revision. Record that configuration commit and their hashes separately from
the immutable image manifest. They use the existing image and grant matrix;
they do not modify it. [Runtime rollout](runtime-rollout.md) owns stopped-role
capture, fresh-cluster restoration, artifact preparation and pre-cutover checks.
The dependency chain does not replace those checks or authorize target changes.

Set `LIBRARIUM_PROJECT_NAME=librarium-beta`, a separate
`LIBRARIUM_DATA_ROOT=/srv/example/appdata/librarium-beta`,
`LIBRARIUM_EDGE_NETWORK=librarium-beta-edge`,
`LIBRARIUM_PUBLIC_ORIGIN=https://lib-beta.example.org`, and `LIBRARIUM_IMAGE`
to the exact approved `ghcr.io/jshauns81/librarium-public@sha256:...` reference. Generate
independent app/database secrets in Dockhand's protected stack environment store.
Create the beta postgres/catalogue directories with the same owner rules as the
existing stack; do not mount writable production paths. Optional files use
`compose.files.yaml` only after actual-kernel acceptance and explicit role choice.
The isolated upstream alias is `librarium-beta-web:8123`. Keep separate beta and
production edge networks and use the existing dedicated-bridge pattern for auth.

A dedicated GitHub classic PAT with only `read:packages` is required for private
GHCR pulls. Store it through Dockhand's registry credentials controls, never in
Compose, Git, releases or command arguments. Do not copy the development GitHub
token into the target. Validate merged runtime JSON using
`python3 scripts/registry_config.py`, comparing protected production JSON with
`--compare` before activation. The checker prints no configuration/credentials.
Release copy is maintained in [the beta release notes](beta-release-notes.md).
Use [private engineering record](agent-environment.md#private-context-discovery) for actual progress;
these instructions are not proof of a successful deployment.

## Build-based candidate path

Use `compose.dockhand.yaml` with context directory `.` only for an explicitly
approved source build. Registry deployments should use the digest-pinned release
path above. Keep automatic deployment and schedules disabled. The
[Dockhand manual](https://dockhand.pro/manual/#git-stacks) describes Git stacks
and protected environment overrides. Configure `LIBRARIUM_PUBLIC_ORIGIN` privately;
there is no built-in personal domain. Migration, web and worker roles remain
separate, and this candidate does not seed fictional data automatically.

## Prepare persistent paths and secrets

On Unraid create a dedicated appdata root and its children before deployment,
for example:

```sh
mkdir -p /srv/example/appdata/librarium/postgres /srv/example/appdata/librarium/catalogue
```

These are example target paths, not directories the agent created remotely.
Select the appdata share/pool according to the existing Unraid storage policy;
the PostgreSQL path must support normal database filesystem semantics. Back up
with `pg_dump` rather than copying live database files. Bind mounts refuse to
silently create a misspelled path. PostgreSQL's entrypoint manages its data
directory permissions. The app runs as UID 10001; snapshot directories/files
must allow that UID to read/traverse them, without granting writes.

Ensure the database image's runtime user can traverse the parent `postgres/`
directory after privilege drop. Correct ownership only on approved new paths;
do not recursively change unrelated appdata or library permissions. Keep actual
installation findings and ownership changes in private context.

Set these in Dockhand's stack environment/secrets controls:

| Variable | Value |
|---|---|
| `LIBRARIUM_DATA_ROOT` | Absolute chosen appdata root, e.g. `/srv/example/appdata/librarium` |
| `LIBRARIUM_SECRET_KEY` | Independently generated random value of at least 50 characters |
| `LIBRARIUM_DB_PASSWORD` | Separate random PostgreSQL password |
| `LIBRARIUM_EDGE_NETWORK` | `librarium-edge`, or a dedicated unused Docker network name |
| `LIBRARIUM_CATALOGUE_DIR` | Leave empty until a published snapshot is staged; then `/catalogue` |
| `LIBRARIUM_IMAGE` | Optional local image name; default `librarium:local-candidate` |

Generate secrets privately, for example `python3 -c 'import secrets; print(secrets.token_urlsafe(60))'`
on a trusted host, and paste them into Dockhand. Never put them in Git, chat,
PR bodies or image build arguments. The Compose environment passes them only at
runtime. Changing the database environment password does not rotate an existing
PostgreSQL role; handle rotation separately. The secret key must remain stable
across container replacement. [Dockhand's environment controls](https://dockhand.pro/manual/)
interpolate these values through the explicit Compose `environment` entries.

`postgres/` owns only Librarium application/job state. `catalogue/` mounts
read-only at `/catalogue`. Do not mount Calibre databases, books, LF state or
writer sockets into this candidate. No catalogue is downloaded automatically.
The [reader contract](development.md#read-only-catalogue-connection) describes
`current`, immutable versioned SQLite files and version/digest binding.

## Connect the authenticated proxy

The stack creates a dedicated bridge network named by `LIBRARIUM_EDGE_NETWORK`.
Attach the existing reverse proxy to that network using its normal management
configuration. Route `lib.example.org` to **`http://librarium-web:8123`**.
There is no published host port; PostgreSQL and the worker stay on the private
internal network. Do not replace the private network with host networking.

Where the proxy cannot join the application network directly, use a separately
managed, digest-pinned bridge that preserves Host and sets HTTPS forwarding.
Keep actual provider IDs, network bindings, routes and managed paths in private
context. Preserve any approved bridge during application updates.

The proxy must:

- Terminate valid HTTPS for `lib.example.org`.
- Enforce Authentik on the whole application, including `/api/*` and assets.
- Preserve `Host: lib.example.org` and set `X-Forwarded-Proto: https`, replacing
  any client-supplied forwarding header. Django trusts that header only because
  the private app endpoint is restricted to the managed proxy network.
- Pass normal methods, bodies, query strings and cookies unchanged. Keep request
  deadlines suitable for the short API calls; background work runs in the worker.

There is no native Librarium login yet. Edge authentication is a deployment
boundary, not an app-verified identity claim. Only trusted proxy containers should
join this network. An unauthenticated browser must be challenged by Authentik
before any application/API response. Container health uses loopback `/api/health`;
there is no need to add a public authentication exception for it.

Configured public mode restricts hosts and CSRF origins to the selected HTTPS
origin, uses secure CSRF cookies and redirects HTTP at both static and API
boundaries. HSTS is initially one hour without subdomain/preload promises. Django
therefore reports W005/W021 in `check --deploy`; those two omissions are deliberate.
[Django's proxy setting](https://docs.djangoproject.com/en/6.1/ref/settings/#secure-proxy-ssl-header)
requires the proxy header guarantees above. No DNS, certificate, Authentik or
proxy configuration was changed by the packaging work itself. Target approvals
and installation evidence belong in private context.

## First installation checks

1. `db` becomes healthy, `initialize` exits 0, and `web` becomes healthy.
2. Confirm Authentik blocks an unauthenticated request to `/`, `/api/session` and
   `/api/works`. Then authenticate and confirm the app and local assets load.
3. The initial collection is empty. Catalogue says no connection until the
   selected snapshot is staged and configured. Do not enable demo data on a real
   installation just to make the page look populated.
4. After snapshot staging, browse/search and open evidence; check version and
   ownership wording. Existing library services remain authoritative.
5. Recreate only this stack's web/worker and confirm state and readiness remain.
   Do not stop other stacks or resume the paused LF heartbeat.

The `Container acceptance` GitHub workflow builds the real image on an isolated
Linux Docker runner. It checks empty installation, packaged assets, secure
cookie/CSRF requests, independent worker completion, container replacement and
dump/restore into a separate database. It deploys nothing and publishes no
image. Check its result for the PR's exact code revision before installing.
Unraid filesystem, proxy/Authentik and LAN behavior still require target checks.

## Backup, update and rollback

Use Dockhand's terminal or a trusted Unraid shell for this stack only. Take a
custom-format `pg_dump -U librarium -d librarium -Fc` from the `db` container and
store it outside replaceable containers. Record the source/image commit and
catalogue snapshot version/digest alongside the backup. Test restore into a
**separate** disposable database before relying on the backup. Credentials are
not part of that metadata.

For beta/stable versions and the planned transition to registry digest pulls,
follow [the release policy](releases.md). Use the build-on-deploy procedure below for a source build.

Before an update, save the database backup and retain the old built image tag.
Set `LIBRARIUM_IMAGE` to a revision-specific local tag for reproducible retention;
select the reviewed Git revision and build/deploy it explicitly. Migrations run
before web/worker start using Compose completion dependencies. A schema change
can make image-only rollback unsafe: restore a verified matching database backup
or use a reviewed reversible migration. Do not blindly reverse a populated schema.
Only the initial schema and current no-schema-change candidate have been exercised;
future-version compatibility and target recovery remain release gates.

The maintainer plans to stop LF/BLC development for a stable baseline. Capture exact source
commits and immutable published data once he confirms that freeze; stopping
development alone does not stop a running harvester. No service was stopped here.
