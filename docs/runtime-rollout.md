# Runtime admission and preserved-state rollout

The workspace entry reuses the registry, native-library, preserved-file and
assessment owners. `compose.runtime.yaml` adds one-shot bootstrap dependencies:

1. `initialize` runs owner migrations.
2. `runtime-login` uses the same pinned PostgreSQL image to create the absent
   `librarium_runtime` login. Its password comes from a dedicated environment
   field through psql input, never command arguments. Existing passwords are not
   rotated. SQL echo, error-statement and transaction-sampling output are disabled
   before password interpolation; client failures produce only a generic refusal.
3. `provision` runs the existing owner-only grant matrix in the app image.
4. `runtime-ready` connects with the actual runtime credentials and checks its
   effective identity, attributes, memberships, ownership and effective grants.
5. Only successful completion admits web and worker with runtime credentials.

The database owner is needed only by migration/bootstrap. Runtime roles have no
owner secret. The checker rejects `LIBRARIUM_RUNTIME_DB_USER/PASSWORD` by presence,
including empty values, because application settings otherwise prefer those keys.
The external Compose variable is not an application environment override.

The SQL and Python check are configuration-mounted source, not new image contents.
Record their exact Git revision/hashes separately from image provenance. Reusing
an older immutable app image requires actual acceptance of that digest with the
selected configuration; configuration parsing alone establishes no compatibility.
The required image gate executes this chain, observes `current_user` in both
foreground roles, exercises permission denials and refuses foreground admission
after failed provisioning, an incorrect existing password or an elevated login.

## Before migration and user admission

Do not update a running stack's image or configuration and assume dependency
ordering stops its old processes. Stop new admission, drain work, inspect exact
project/name/container identities and stop only the selected web and worker using
the supported per-container controls. Verify both stopped and PostgreSQL healthy
before capture. Stack-wide stop would also stop the database required by pg_dump.

Retain a coordinated pre-migration database and every referenced immutable artifact,
with the old image, schema, configuration and input pins. A missing old artifact
mount does not establish that no historical row references artifacts; inspect the
recorded job kinds/bindings and capture everything referenced. Hash and restore-check
this generation before any deploy can run new migrations.

Exercise the restored candidate generation on separate, unpublished state/network.
Verify actual kernel restrictions, artifact locking/durability/ownership, capacity,
runtime grants and preserved evidence there. Take and restore-check a post-migration
capture before cutover or accepting user work. A successful ordinary all-services
deploy proves neither backup acceptance nor actual target isolation.

## Fresh restoration and rollback

Post-migration dumps may contain ACLs naming a runtime login absent from a new
cluster. Restore with `pg_restore --exit-on-error --no-privileges`, then explicitly
create/provision/verify the selected runtime before foreground admission. Never
ignore restore errors. The required acceptance uses a different PostgreSQL cluster,
proves the login is initially absent, reproduces the old ACL restore refusal and
reopens saved job keys, source/report and held-output bindings after reprovisioning.

Image-only rollback cannot reverse schema changes. Restore a retained generation
into a separate fresh PostgreSQL directory with compatible code; preserve the
migrated directory and evidence history. Never drop/recreate the original database
or remove evidence to make a reversal pass. Disclose later work absent from the
selected generation before restoration; prefer a reviewed fix-forward where needed.

## Prepared storage and disposable resources

File-role binds refuse automatic host-path creation. Prepare a fresh artifact root
under the selected beta state directory, owned by 10001:10001 and mode 0700, before
enabling the role. Verify the parent, ownership and absence of unsafe/symlink paths.
Do not recursively repair an unknown existing tree. An explicit directory-bootstrap
resource may require narrowly selected ownership capabilities; a root process with
all capabilities dropped cannot be assumed able to chown files.

Disposable probe names must be confirmed absent with successful inventory evidence
and an independently known anchor; an empty error response is not absence. Create
with start disabled, inspect the submitted definition, then deploy. Kernel probes
use the exact accepted image, no network, a read-only root, dropped capabilities,
no-new-privileges and only their owned subtree. No secrets, privileged mode, host
control socket or unrelated mounts belong there. Add read-only inputs only when
the particular test requires them. Keep directory-bootstrap privileges separate.

Remove only owned probe resources with volume deletion disabled, preserve audit
configuration and verify containers gone. Bounded remote exec may buffer output
or misreport a missing exit status: use internal time limits, controlled backup
files and explicit completion markers with hashes/sizes. Never stream a target
database dump through its stdout. HTTP timeout alone proves no process termination.

Target configuration, resource authority, authenticated sessions and human
acceptance remain separate. Successful runner isolation does not certify a target
kernel; an unavailable sandbox keeps preserved-file processing disabled.
