#!/bin/bash
# Cloud-only session bootstrap: start PostgreSQL 18.6 and keep pinned deps current.
# Toolchains come from the environment setup script; this only does per-session work.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
log=/tmp/librarium-session-start.log
exec >>"$log" 2>&1

# PostgreSQL 18.6, disposable, loopback only.
if ! docker info >/dev/null 2>&1; then
  (dockerd >/var/log/dockerd.log 2>&1 &)
  for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
fi
docker start librarium-pg >/dev/null 2>&1 || docker run -d --name librarium-pg \
  -e POSTGRES_USER=librarium -e POSTGRES_DB=librarium -e POSTGRES_PASSWORD="$PGPASSWORD" \
  -p 127.0.0.1:5432:5432 \
  postgres:18.6-bookworm@sha256:bbf83594798e144bff365a9c191c5d779f181fb3135902064ab8ff11918020fc
docker inspect librarium-pg >/dev/null 2>&1 &&
  for _ in $(seq 1 30); do docker exec librarium-pg pg_isready -U librarium -d librarium >/dev/null 2>&1 && break; sleep 1; done

# Native inputs, if the setup script ran before the clone existed.
[ -f "$LIBARCHIVE" ] || uv run --frozen python scripts/build_libarchive.py \
  --prefix /opt/librarium/libarchive --build-dir /tmp/libarchive-build
[ -d "$LIBRARIUM_EPUBCHECK_DIR" ] || uv run --frozen python scripts/install_epubcheck.py \
  --prefix "$LIBRARIUM_EPUBCHECK_DIR"

uv sync --frozen
stamp=frontend/node_modules/.librarium-ci.sha256
sha256sum --check --status "$stamp" 2>/dev/null || {
  rm -f "$stamp"
  npm --prefix frontend ci --no-audit --no-fund &&
    sha256sum frontend/package.json frontend/package-lock.json > "$stamp"
}
exit 0
