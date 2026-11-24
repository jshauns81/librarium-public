#!/bin/sh
set -eu
: "${LIBRARIUM_CALIBRE_RUNTIME:?pinned Calibre runtime required}"
: "${LIBARCHIVE:?built libarchive required}"
: "${LIBRARIUM_EPUBCHECK_DIR:?verified EPUBCheck required}"
: "${LIBRARIUM_JAVA:?Java required}"
: "${PGHOST:?isolated PostgreSQL socket required}"
: "${PGDATABASE:?isolated maintenance database required}"
export LIBRARIUM_REQUIRE_NATIVE=1
export LIBRARIUM_WRITER_PORT="${LIBRARIUM_WRITER_PORT:-8133}"
# Native proofs share fixed ports and process state, so keep both invocations serial.
uv run pytest -n 0 -W error -q tests/test_calibre_delivery_gate.py tests/test_delivery_native_kills.py

# This proof owns an isolated loopback and a real server; it cannot reach host services.
export LIBRARIUM_CALIBRE_PORT="${LIBRARIUM_CALIBRE_PORT:-8134}"
unshare --user --map-root-user --net sh -c 'ip link set lo up; exec uv run pytest -n 0 -W error -q tests/test_delivery_content_server_native.py'
