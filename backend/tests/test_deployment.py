import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def settings_result(origin="https://lib.example.org", trust="1"):
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "DJANGO_SETTINGS_MODULE": "librarium.settings",
        "LIBRARIUM_SECRET_KEY": "deployment-test-key-" * 5,
        "LIBRARIUM_PUBLIC_ORIGIN": origin,
        "LIBRARIUM_TRUST_PROXY": trust,
    }
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings as s; import json; print(json.dumps({'hosts':s.ALLOWED_HOSTS,'origins':s.CSRF_TRUSTED_ORIGINS,'secure':s.CSRF_COOKIE_SECURE,'proxy':s.SECURE_PROXY_SSL_HEADER,'redirect':s.SECURE_SSL_REDIRECT,'reference_state':getattr(s,'LIBRARIUM_REFERENCE_STATE_DIR',None)}))",
        ],
        cwd=ROOT,
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )


def test_public_origin_has_explicit_https_proxy_and_cookie_settings():
    result = settings_result()
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert "lib.example.org" in values["hosts"]
    assert "*" not in values["hosts"]
    assert values["origins"] == ["https://lib.example.org"]
    assert values["secure"] is True
    assert values["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]
    assert values["redirect"] is True


@pytest.mark.parametrize(
    "origin,trust",
    [
        ("http://lib.example.org", "1"),
        ("https://user:pass@lib.example.org", "1"),
        ("https://lib.example.org/path", "1"),
        ("https://lib.example.org", "0"),
        ("https://lib.example.org?x=1", "1"),
    ],
)
def test_invalid_public_configuration_refuses_to_start(origin, trust):
    assert settings_result(origin, trust).returncode != 0


def test_local_configuration_retains_loopback_development():
    result = settings_result("", "0")
    assert result.returncode == 0
    values = json.loads(result.stdout)
    assert "lib.example.org" not in values["hosts"]
    assert values["secure"] is False
    assert values["proxy"] is None


@pytest.mark.parametrize("path", ["relative/state", "/reference/../books", "/reference//state"])
def test_reference_producer_rejects_noncanonical_state_paths(monkeypatch, path):
    monkeypatch.setenv("LIBRARIUM_REFERENCE_STATE_DIR", path)
    assert settings_result("", "0").returncode != 0


def test_reference_producer_state_is_explicit_and_optional(monkeypatch):
    monkeypatch.delenv("LIBRARIUM_REFERENCE_STATE_DIR", raising=False)
    assert json.loads(settings_result("", "0").stdout)["reference_state"] == ""
    monkeypatch.setenv("LIBRARIUM_REFERENCE_STATE_DIR", "/selected/private/reference")
    result = settings_result("", "0")
    assert result.returncode == 0
    assert json.loads(result.stdout)["reference_state"] == "/selected/private/reference"


@pytest.mark.django_db
def test_health_confirms_database_readiness_without_returning_data(client):
    result = client.get("/api/health")
    assert result.status_code == 200
    assert result.json() == {"status": "ready"}


def test_health_failure_is_generic_and_returns_503(client, monkeypatch):
    from django.db import DatabaseError
    from librarium import views

    def broken():
        raise DatabaseError("private connection details")

    monkeypatch.setattr(views.connection, "cursor", broken)
    result = client.get("/api/health")
    assert result.status_code == 503
    assert result.json() == {"status": "unavailable"}


def test_public_https_assets_receive_hsts(settings):
    from librarium.headers import SecurityHeaders

    settings.ALLOWED_HOSTS = ["lib.example.org"]
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.SECURE_HSTS_SECONDS = 3600
    statuses = []

    def assets(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"assets"]

    response = SecurityHeaders(assets)(
        {
            "HTTP_HOST": "lib.example.org",
            "SERVER_NAME": "lib.example.org",
            "SERVER_PORT": "8123",
            "PATH_INFO": "/assets/app.js",
            "HTTP_X_FORWARDED_PROTO": "https",
        },
        lambda status, headers, *args: statuses.append(dict(headers)),
    )
    assert b"".join(response) == b"assets"
    assert statuses[0]["Strict-Transport-Security"] == "max-age=3600"


def test_public_mode_redirects_static_and_api_http_at_the_outer_boundary(client, settings):
    settings.ALLOWED_HOSTS = ["lib.example.org", "testserver"]
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    from librarium.headers import SecurityHeaders

    called = []

    def application(environ, start_response):
        called.append(True)
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"assets"]

    wrapper = SecurityHeaders(application)
    for path in ["/", "/assets/app.js", "/api/session"]:
        statuses = []
        response = b"".join(
            wrapper(
                {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": path,
                    "QUERY_STRING": "",
                    "SERVER_NAME": "lib.example.org",
                    "SERVER_PORT": "80",
                    "HTTP_HOST": "lib.example.org",
                    "wsgi.url_scheme": "http",
                },
                lambda status, headers, *args, target=statuses: target.append(
                    (status, dict(headers))
                ),
            )
        )
        assert statuses[0][0].startswith("301")
        assert statuses[0][1]["Location"] == f"https://lib.example.org{path}"
        assert response == b""
    assert called == []


@pytest.mark.parametrize(
    "exit_code,diagnostic,accepted",
    [
        (1, "synthetic_only_required", True),
        (1, "runtime_installation_changed", False),
        (1, "writer_disabled", False),
        (0, "synthetic_only_required", False),
    ],
)
def test_image_ci_enabled_launcher_requires_post_exec_refusal(
    tmp_path, exit_code, diagnostic, accepted
):
    import textwrap

    workflow = (ROOT / ".github/workflows/delivery-writer.yml").read_text()
    marker = "      - name: Enabled image launcher reaches synthetic refusal\n        run: |\n"
    assert marker in workflow
    block = workflow.split(marker, 1)[1].split("      - name:", 1)[0]
    script = textwrap.dedent(block)
    docker = tmp_path / "docker"
    docker.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "$RUNNER_TEMP/args"\n'
        f"echo {diagnostic} >&2\nexit {exit_code}\n"
    )
    docker.chmod(0o700)
    result = subprocess.run(
        ["sh", "-eu", "-c", script],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
        },
        check=False,
    )
    assert (result.returncode == 0) is accepted
    args = (tmp_path / "args").read_text().splitlines()
    assert args[:5] == ["run", "--rm", "--network", "none", "--read-only"]
    assert "LIBRARIUM_DELIVERY_ENABLED=1" in args
    assert "--entrypoint" not in args
    assert args[-1] == "librarium-writer-acceptance"
    # The image keeps Calibre's config under /state, which a deployment mounts
    # with its private config directory already present.
    assert any(a.startswith("/state:") and "uid=10001" in a for a in args)
    assert any(a.startswith("/state/config:") and "uid=10001" in a for a in args)
    if not accepted:
        assert diagnostic in result.stdout + result.stderr


def run_workflow_step(tmp_path, name, output, exit_code):
    import textwrap

    workflow = (ROOT / ".github/workflows/delivery-writer.yml").read_text()
    marker = f"      - name: {name}\n        run: |\n"
    assert marker in workflow
    script = textwrap.dedent(workflow.split(marker, 1)[1].split("      - name:", 1)[0])
    (tmp_path / "output").write_text(output)
    docker = tmp_path / "docker"
    docker.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "$RUNNER_TEMP/args"\n'
        f'cat "{tmp_path / "output"}" >&2\nexit {exit_code}\n'
    )
    docker.chmod(0o700)
    result = subprocess.run(
        ["sh", "-eu", "-c", script],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
        },
        check=False,
    )
    return result, (tmp_path / "args").read_text().splitlines()


PLAIN_STATE_REFUSAL = "Writer refused to start: writer_state_unavailable.\n"


@pytest.mark.parametrize(
    "exit_code,output,accepted",
    [
        (1, PLAIN_STATE_REFUSAL, True),
        (1, "Traceback (most recent call last):\nPermissionError: [Errno 13]\n", False),
        (1, "Traceback (most recent call last):\n" + PLAIN_STATE_REFUSAL, False),
        (1, "Writer refused to start: synthetic_only_required.\n", False),
        (0, PLAIN_STATE_REFUSAL, False),
    ],
)
def test_image_ci_enabled_launcher_without_state_requires_plain_refusal(
    tmp_path, exit_code, output, accepted
):
    result, args = run_workflow_step(
        tmp_path,
        "Enabled launcher without a state volume refuses plainly",
        output,
        exit_code,
    )
    assert (result.returncode == 0) is accepted, result.stdout + result.stderr
    assert args[:5] == ["run", "--rm", "--network", "none", "--read-only"]
    assert "LIBRARIUM_DELIVERY_ENABLED=1" in args
    assert "--entrypoint" not in args
    assert not any(a.startswith("/state") for a in args)
    assert args[-1] == "librarium-writer-acceptance"


def writer_image_environment():
    """The writer image's ENV instruction, parsed from Dockerfile.writer."""
    lines = (ROOT / "Dockerfile.writer").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("ENV "))
    words = []
    for line in lines[start:]:
        words += line.removeprefix("ENV ").rstrip("\\").split()
        if not line.endswith("\\"):
            break
    return dict(word.split("=", 1) for word in words)


@pytest.mark.parametrize("volume", ["absent", "without_config"])
def test_enabled_image_launcher_without_state_refuses_before_calibre(tmp_path, volume):
    """Mirrors the image CI step: delivery enabled and no writer state volume mounted."""
    image = writer_image_environment()
    assert image["LIBRARIUM_WRITER_STATE_DIR"] == "/state"
    assert image["CALIBRE_CONFIG_DIRECTORY"] == "/state/config"
    state = tmp_path / "state"
    if volume == "without_config":
        state.mkdir(mode=0o700)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    started = tmp_path / "calibre-started"
    (runtime / "calibre-debug").write_text(f"#!/bin/sh\ntouch '{started}'\n")
    (runtime / "calibre-debug").chmod(0o700)
    env = {
        **{name: value.replace("/state", str(state)) for name, value in image.items()},
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "LIBRARIUM_DELIVERY_ENABLED": "1",
        # Never read: the state check runs before runtime verification.
        "LIBRARIUM_WRITER_ARCHIVE": str(tmp_path / "absent-archive.txz"),
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_delivery_writer.py"), "--runtime", str(runtime)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        (
            "Writer refused to start: writer_state_unavailable. LIBRARIUM_WRITER_STATE_DIR "
            "and its config directory must be existing private directories that the writer "
            "user owns and can write."
        )
    ]
    assert str(tmp_path) not in result.stderr
    assert not started.exists()
    assert not (state / "config").exists()
    assert state.is_dir() is (volume == "without_config")


def test_native_role_proof_postgres_port_matches_exported_pgport():
    import re

    workflow = (ROOT / ".github/workflows/delivery-writer.yml").read_text()
    marker = "      - name: Isolated socket-only PostgreSQL and namespace prerequisites\n"
    block = workflow.split(marker, 1)[1].split("      - name:", 1)[0]
    server = re.search(r"pg_ctl [^\n]*-o \"[^\"]*-p (\d+)", block)
    exported = re.search(r'echo "PGPORT=(\d+)" >> "\$GITHUB_ENV"', block)
    assert server and exported, "the proof reads PGPORT; the server must listen on it"
    assert server.group(1) == exported.group(1)


def test_writer_image_archive_is_readable_by_the_unprivileged_writer():
    # ADD from a URL creates a root-owned 0600 file; the writer (uid 10001)
    # must read it to verify the installed runtime before exec.
    dockerfile = (ROOT / "Dockerfile.writer").read_text()
    assert "USER 10001" in dockerfile
    assert "chmod 0444 /opt/calibre-archive.txz" in dockerfile
    # The pinned archive ships resources/locales as 0700; root extraction keeps it.
    assert "chmod -R a+rX /opt/calibre" in dockerfile


def test_writer_image_installs_the_gl_runtime_qtgui_needs():
    import re

    # Calibre's PyQt6.QtGui links libGLX.so.0; without it image handling fails.
    dockerfile = (ROOT / "Dockerfile.writer").read_text()
    install = dockerfile.split("apt-get install", 1)[1].split("&&", 1)[0]
    assert "libgl1" in re.findall(r"[a-z0-9][a-z0-9.+-]*", install)
