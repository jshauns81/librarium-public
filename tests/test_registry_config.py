import copy
import json
import subprocess
from pathlib import Path

import pytest

from scripts.registry_config import RUNTIME_LOGIN_COMMAND
from scripts.registry_config import check as validate_config

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/registry_config.py"
IMAGE = "ghcr.io/jshauns81/librarium-public@sha256:" + "a" * 64


def config(name="librarium-beta"):
    env = {
        "LIBRARIUM_PUBLIC_ORIGIN": "https://lib-beta.example.org",
        "LIBRARIUM_TRUST_PROXY": "1",
        "LIBRARIUM_SECRET_KEY": "beta-" + "x" * 60,
        "PGPASSWORD": "beta-password",
        "PGUSER": "librarium",
        "PGHOST": "db",
        "PGPORT": "5432",
        "PGDATABASE": "librarium",
    }
    return {
        "name": name,
        "networks": {"default": {"internal": True}, "edge": {"name": name + "-edge"}},
        "services": {
            "db": {
                "image": "postgres:18.6-bookworm@sha256:" + "d" * 64,
                "environment": {
                    "POSTGRES_USER": "librarium",
                    "POSTGRES_PASSWORD": "beta-password",
                    "POSTGRES_DB": "librarium",
                },
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/appdata/" + name + "/postgres",
                        "target": "/var/lib/postgresql",
                    }
                ],
            },
            "initialize": {"image": IMAGE, "environment": env},
            "worker": {"image": IMAGE, "environment": env, "volumes": []},
            "web": {
                "image": IMAGE,
                "environment": env,
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/appdata/" + name + "/catalogue",
                        "target": "/catalogue",
                        "read_only": True,
                    }
                ],
                "networks": {"default": {}, "edge": {"aliases": [name + "-web"]}},
            },
        },
    }


def check(candidate, production=None, tmp_path=None):
    args = ["python3", str(SCRIPT)]
    if production:
        p = tmp_path / "production.json"
        p.write_text(json.dumps(production))
        args += ["--compare", str(p)]
    return subprocess.run(
        args, input=json.dumps(candidate), text=True, capture_output=True, check=False
    )


def test_accepts_isolated_digest_config():
    result = check(config())
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("peers", ["", "192.0.2.10", "192.0.2.10,2001:db8::10"])
def test_operator_proxy_configuration_is_optional_and_web_only(peers):
    value = copy.deepcopy(config())
    value["services"]["web"]["environment"] = {
        **value["services"]["web"]["environment"], "LIBRARIUM_OPERATOR_PROXY_IPS": peers,
    }
    result = check(value)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("role", ["db", "initialize", "worker", "provision", "runtime-ready",
                                  "runtime-login"])
@pytest.mark.parametrize("peers", ["", "192.0.2.10"])
def test_operator_identity_environment_is_refused_outside_web(role, peers):
    value = copy.deepcopy(runtime_config())
    value["services"][role]["environment"] = {
        **value["services"][role]["environment"], "LIBRARIUM_OPERATOR_PROXY_IPS": peers,
    }
    with pytest.raises(ValueError, match="operator identity"):
        validate_config(value)


@pytest.mark.parametrize("key,peers", [
    ("LIBRARIUM_OPERATOR_PROXY_IPS", "*"),
    ("LIBRARIUM_OPERATOR_PROXY_IPS", "192.0.2.0/24"),
    ("LIBRARIUM_OPERATOR_PROXY_IPS", "proxy.example.org"),
    ("LIBRARIUM_OPERATOR_PROXY_IPS", "192.0.2.10,"),
    ("LIBRARIUM_OPERATOR_PROXY_IPS", "fe80::1%eth0"),
    ("LIBRARIUM_OPERATOR_HEADER", "Remote-User"),
])
def test_operator_identity_configuration_is_narrow(key, peers):
    value = copy.deepcopy(config())
    value["services"]["web"]["environment"] = {
        **value["services"]["web"]["environment"], key: peers,
    }
    with pytest.raises(ValueError, match="operator identity"):
        validate_config(value)


@pytest.mark.parametrize("role", ["cover-sources", "catalogue-relay"])
def test_operator_identity_is_refused_on_optional_network_roles(tmp_path, role):
    value = cover_sources_config() if role == "cover-sources" else relay_config(tmp_path)[0]
    value["services"][role]["environment"] = {
        **value["services"][role].get("environment", {}),
        "LIBRARIUM_OPERATOR_PROXY_IPS": "192.0.2.10",
    }
    with pytest.raises(ValueError, match="operator identity"):
        validate_config(value)


def cover_sources_config(*, provisioned=False):
    value = copy.deepcopy(runtime_config() if provisioned else config())
    value["networks"].update(
        {
            "cover-control": {"internal": True},
            "cover-egress": {"internal": False},
        }
    )
    value["networks"]["edge"]["internal"] = True
    worker = value["services"]["worker"]
    worker["environment"] = dict(worker["environment"])
    worker["networks"] = {"default": {}, "cover-control": {}}
    worker["environment"]["LIBRARIUM_COVER_SOURCES_SECRET"] = "x" * 32
    value["services"]["cover-sources"] = {
        "image": IMAGE,
        "profiles": ["cover-sources"],
        "user": "10001:10001",
        "command": ["python", "-m", "librarium.cover_source_server"],
        "environment": {
            "LIBRARIUM_COVER_SOURCES_SECRET": "x" * 32,
            "HARDCOVER_TOKEN": "",
        },
        "read_only": True,
        "tmpfs": ["/tmp:size=32m,mode=1777"],
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "init": True,
        "mem_limit": 512 * 1024 * 1024,
        "pids_limit": 32,
        "cpus": 1,
        "restart": "unless-stopped",
        "networks": {
            "cover-control": {"aliases": ["cover-control-listener"]},
            "cover-egress": {},
        },
    }
    return value


def source_browser_config():
    import yaml

    value = cover_sources_config()
    overlay = yaml.safe_load(
        (SCRIPT.parent.parent / "compose.source-browser.yaml").read_text()
    )
    role = overlay["services"]["source-browser"]
    role["image"] = "ghcr.io/jshauns81/librarium-public-source-browser@sha256:" + "b" * 64
    role["environment"]["LIBRARIUM_SOURCE_BROWSER_SECRET"] = "browser-" + "y" * 32
    role["volumes"] = [
        {
            "type": "volume",
            "source": "source-browser-profile",
            "target": "/data",
            "volume": {},
        }
    ]
    value["services"]["source-browser"] = role
    value["services"]["worker"]["networks"]["source-browser-control"] = {}
    value["services"]["worker"]["environment"]["LIBRARIUM_SOURCE_BROWSER_SECRET"] = (
        role["environment"]["LIBRARIUM_SOURCE_BROWSER_SECRET"]
    )
    value["networks"]["source-browser-control"] = {"internal": True}
    value["volumes"] = {
        "source-browser-profile": {"name": value["name"] + "_source-browser-profile"}
    }
    return value


def test_source_browser_overlay_is_admitted():
    result = check(source_browser_config())
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "root",
        "capability",
        "no-seccomp",
        "writable",
        "db-network",
        "web-network",
        "web-secret",
        "db-secret",
        "wrong-secret",
        "db-env",
        "mount",
        "shared-volume",
        "bind-volume",
        "external-volume",
        "command",
        "entrypoint",
        "image",
        "port",
        "unbounded",
        "public-control",
        "unknown-setting",
    ],
)
def test_browser_overlay_cannot_relax_isolation(mutation):
    value = source_browser_config()
    role = value["services"]["source-browser"]
    if mutation == "root":
        role["user"] = "0:0"
    elif mutation == "capability":
        role["cap_add"] = ["SYS_ADMIN"]
    elif mutation == "no-seccomp":
        role["security_opt"] = ["no-new-privileges:true"]
    elif mutation == "writable":
        role["read_only"] = False
    elif mutation == "db-network":
        role["networks"]["default"] = {}
    elif mutation == "web-network":
        value["services"]["web"]["networks"]["source-browser-control"] = {}
    elif mutation in {"web-secret", "db-secret"}:
        value["services"][mutation.split("-")[0]]["environment"][
            "LIBRARIUM_SOURCE_BROWSER_SECRET"
        ] = "leak"
    elif mutation == "wrong-secret":
        role["environment"]["LIBRARIUM_SOURCE_BROWSER_SECRET"] = "z" * 32
    elif mutation == "db-env":
        role["environment"]["PGPASSWORD"] = "leak"
    elif mutation == "mount":
        role["volumes"].append(
            {"type": "bind", "source": "/example/library", "target": "/library"}
        )
    elif mutation == "shared-volume":
        value["services"]["worker"]["volumes"] = role["volumes"]
    elif mutation == "bind-volume":
        role["volumes"][0]["type"] = "bind"
    elif mutation == "external-volume":
        value["volumes"]["source-browser-profile"]["external"] = True
    elif mutation == "command":
        role["command"] = ["sh"]
    elif mutation == "entrypoint":
        role["entrypoint"] = ["sh"]
    elif mutation == "image":
        role["image"] = IMAGE
    elif mutation == "port":
        role["ports"] = ["8126:8126"]
    elif mutation == "unbounded":
        role["pids_limit"] = -1
    elif mutation == "public-control":
        value["networks"]["source-browser-control"]["internal"] = False
    else:
        role["env_file"] = ["unexpected.env"]
    assert check(value).returncode != 0


@pytest.mark.parametrize("provisioned", [False, True])
def test_cover_sources_overlay_is_admitted(provisioned):
    result = check(cover_sources_config(provisioned=provisioned))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-role",
        "source-default",
        "web-control",
        "worker-egress",
        "db-control",
        "public-edge",
        "public-control",
        "external-egress",
        "host-driver",
        "bridge-options",
        "source-mount",
        "source-db-env",
        "source-secret-mount",
        "source-entrypoint",
        "source-command",
        "source-root",
        "source-writable",
        "source-capabilities",
        "source-unbounded",
        "source-port",
        "wrong-image",
        "wrong-alias",
        "wrong-secret",
        "missing-secret",
        "web-secret",
    ],
)
def test_cover_sources_overlay_cannot_relax_isolation(mutation):
    value = cover_sources_config()
    services, networks = value["services"], value["networks"]
    source = services["cover-sources"]
    if mutation == "unknown-role":
        services["other-sources"] = services.pop("cover-sources")
    elif mutation in {"source-default", "web-control", "worker-egress", "db-control"}:
        role, network = {
            "source-default": ("cover-sources", "default"),
            "web-control": ("web", "cover-control"),
            "worker-egress": ("worker", "cover-egress"),
            "db-control": ("db", "cover-control"),
        }[mutation]
        services[role].setdefault("networks", {"default": {}})[network] = {}
    elif mutation in {"public-edge", "public-control"}:
        networks["edge" if mutation == "public-edge" else "cover-control"][
            "internal"
        ] = False
    elif mutation == "external-egress":
        networks["cover-egress"]["external"] = True
    elif mutation == "host-driver":
        networks["cover-control"]["driver"] = "host"
    elif mutation == "bridge-options":
        networks["cover-egress"]["driver_opts"] = {
            "com.docker.network.bridge.name": "unsafe"
        }
    elif mutation == "wrong-alias":
        source["networks"]["cover-control"]["aliases"] = ["wrong-listener"]
    elif mutation in {"wrong-secret", "missing-secret"}:
        source["environment"]["LIBRARIUM_COVER_SOURCES_SECRET"] = (
            "wrong" if mutation == "wrong-secret" else ""
        )
    elif mutation == "web-secret":
        services["web"]["environment"]["LIBRARIUM_COVER_SOURCES_SECRET"] = "x" * 32
    else:
        key, bad = {
            "source-mount": (
                "volumes",
                [{"type": "bind", "source": "/data", "target": "/library"}],
            ),
            "source-db-env": (
                "environment",
                {**source["environment"], "PGPASSWORD": "unsafe"},
            ),
            "source-secret-mount": ("secrets", [{"source": "unsafe"}]),
            "source-entrypoint": ("entrypoint", ["sh"]),
            "source-command": ("command", ["sh"]),
            "source-root": ("user", "0:0"),
            "source-writable": ("read_only", False),
            "source-capabilities": ("cap_add", ["NET_ADMIN"]),
            "source-unbounded": ("mem_limit", 0),
            "source-port": ("ports", [8124]),
            "wrong-image": ("image", IMAGE.replace("a" * 64, "b" * 64)),
        }[mutation]
        source[key] = bad
    assert check(value).returncode == 1


@pytest.mark.parametrize("overlay", [False, True], ids=["base", "cover-sources"])
def test_resolved_registry_compose_config_is_admitted(overlay):
    import os
    import shutil

    if not shutil.which("docker"):
        pytest.skip("Docker Compose is unavailable")
    env = {
        "PATH": os.environ["PATH"],
        "LIBRARIUM_PROJECT_NAME": "librarium-fixture",
        "LIBRARIUM_IMAGE": IMAGE,
        "LIBRARIUM_DB_PASSWORD": "fixture-password",
        "LIBRARIUM_SECRET_KEY": "x" * 64,
        "LIBRARIUM_PUBLIC_ORIGIN": "https://lib.example.org",
        "LIBRARIUM_DATA_ROOT": "/appdata/librarium-fixture",
        "LIBRARIUM_EDGE_NETWORK": "fixture-edge",
        "LIBRARIUM_COVER_SOURCES_ENABLED": "true",
        "LIBRARIUM_COVER_SOURCES_SECRET": "x" * 32,
    }
    command = ["docker", "compose", "-f", "compose.registry.yaml"]
    if overlay:
        command += ["-f", "compose.cover-sources.yaml", "--profile", "cover-sources"]
    resolved = subprocess.run(
        command + ["config", "--format", "json"],
        env=env,
        cwd=SCRIPT.parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    result = check(json.loads(resolved.stdout))
    assert result.returncode == 0, result.stderr


def split_credentials_config():
    value = copy.deepcopy(assessment_config())
    for role in ("initialize", "web", "worker"):
        value["services"][role]["environment"] = dict(
            value["services"][role]["environment"],
            PGUSER="librarium" if role == "initialize" else "librarium_runtime",
            PGPASSWORD="owner-password" if role == "initialize" else "runtime-password",
            PGHOST="db",
            PGPORT="5432",
            PGDATABASE="librarium",
        )
    value["services"]["db"]["environment"] = {
        "POSTGRES_USER": "librarium",
        "POSTGRES_PASSWORD": "owner-password",
        "POSTGRES_DB": "librarium",
    }
    return value


def test_accepts_separate_owner_and_matching_runtime_credentials():
    result = check(runtime_config())
    assert result.returncode == 0, result.stderr
    assert "owner-password" not in result.stdout + result.stderr
    assert "runtime-password" not in result.stdout + result.stderr


@pytest.mark.parametrize("role", ["initialize", "web", "worker"])
@pytest.mark.parametrize(
    "key", ["LIBRARIUM_RUNTIME_DB_USER", "LIBRARIUM_RUNTIME_DB_PASSWORD"]
)
def test_runtime_shadow_environment_is_refused_even_when_empty(role, key):
    value = copy.deepcopy(config())
    value["services"][role]["environment"] = dict(
        value["services"][role]["environment"]
    )
    value["services"][role]["environment"][key] = ""
    assert check(value).returncode == 1


def test_split_runtime_cannot_be_admitted_without_the_provisioning_chain():
    assert check(split_credentials_config()).returncode == 1


@pytest.mark.parametrize(
    "mutation", ["worker_host", "worker_database", "database_password"]
)
def test_shared_login_still_requires_selected_database_and_owner_binding(mutation):
    value = split_credentials_config()
    for role in ("web", "worker"):
        value["services"][role]["environment"].update(
            PGUSER="librarium", PGPASSWORD="owner-password"
        )
    if mutation == "database_password":
        value["services"]["db"]["environment"]["POSTGRES_PASSWORD"] = "another-password"
    else:
        key = "PGHOST" if mutation == "worker_host" else "PGDATABASE"
        value["services"]["worker"]["environment"][key] = "another"
    assert check(value).returncode == 1


def test_split_owner_password_cannot_be_empty_even_when_database_matches():
    value = split_credentials_config()
    value["services"]["initialize"]["environment"]["PGPASSWORD"] = ""
    value["services"]["db"]["environment"]["POSTGRES_PASSWORD"] = ""
    assert check(value).returncode == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "runtime_user",
        "runtime_password",
        "owner_user",
        "owner_password",
        "shared_password",
        "database",
        "host",
        "missing_user",
    ],
)
def test_split_credentials_refuse_misbound_roles_without_printing_secrets(mutation):
    value = runtime_config()
    services = value["services"]
    if mutation == "runtime_user":
        services["worker"]["environment"]["PGUSER"] = "another_runtime"
    elif mutation == "runtime_password":
        services["worker"]["environment"]["PGPASSWORD"] = "another-password"
    elif mutation == "owner_user":
        services["initialize"]["environment"]["PGUSER"] = "another_owner"
    elif mutation == "owner_password":
        services["initialize"]["environment"]["PGPASSWORD"] = "another-password"
    elif mutation == "shared_password":
        for role in ("web", "worker"):
            services[role]["environment"]["PGPASSWORD"] = "owner-password"
    elif mutation in {"database", "host"}:
        key = "PGDATABASE" if mutation == "database" else "PGHOST"
        services["worker"]["environment"][key] = "another"
    else:
        services["worker"]["environment"].pop("PGUSER")
    result = check(value)
    assert result.returncode == 1
    assert "owner-password" not in result.stdout + result.stderr
    assert "runtime-password" not in result.stdout + result.stderr


def test_split_beta_credentials_are_compared_to_all_production_database_roles(tmp_path):
    beta, prod = runtime_config(), runtime_config()
    prod["name"] = "librarium-production"
    prod["networks"]["edge"]["name"] = "production-edge"
    for service in prod["services"].values():
        for mount in service.get("volumes", []):
            mount["source"] = "/production" + mount["source"]
        env = service.get("environment", {})
        for key in (
            "PGPASSWORD",
            "POSTGRES_PASSWORD",
            "RUNTIME_PASSWORD",
            "LIBRARIUM_SECRET_KEY",
        ):
            if key in env:
                env[key] = "production-" + env[key]
        if "LIBRARIUM_PUBLIC_ORIGIN" in env:
            env["LIBRARIUM_PUBLIC_ORIGIN"] = "https://lib.example.org"
    assert check(beta, prod, tmp_path).returncode == 0
    for beta_role in ("initialize", "web"):
        for prod_role in ("initialize", "worker"):
            candidate = copy.deepcopy(beta)
            password = prod["services"][prod_role]["environment"]["PGPASSWORD"]
            roles = ("initialize",) if beta_role == "initialize" else ("web", "worker")
            for role in roles:
                candidate["services"][role]["environment"]["PGPASSWORD"] = password
            if beta_role == "initialize":
                candidate["services"]["db"]["environment"]["POSTGRES_PASSWORD"] = (
                    password
                )
            assert check(candidate, prod, tmp_path).returncode == 1


def runtime_config():
    value = split_credentials_config()
    services = value["services"]
    for name, env_source in [
        ("runtime-login", "initialize"),
        ("provision", "initialize"),
        ("runtime-ready", "web"),
    ]:
        services[name] = {
            "image": services["db"]["image"] if name == "runtime-login" else IMAGE,
            "environment": dict(services[env_source]["environment"]),
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "restart": "no",
        }
    services["runtime-login"]["environment"]["RUNTIME_PASSWORD"] = "runtime-password"
    services["provision"]["command"] = [
        "python",
        "manage.py",
        "provision_runtime_role",
        "librarium_runtime",
    ]
    services["runtime-ready"]["command"] = [
        "python",
        "-c",
        "exec(compile(open('/runtime_identity.py').read(), '/runtime_identity.py', 'exec'))",
    ]
    services["runtime-login"]["entrypoint"] = ["/bin/sh", "-ec"]
    services["runtime-login"]["command"] = [RUNTIME_LOGIN_COMMAND]
    services["runtime-login"]["user"] = "postgres"
    for role, filename in [
        ("runtime-login", "runtime_login.sql"),
        ("runtime-ready", "runtime_identity.py"),
    ]:
        services[role]["volumes"] = [
            {
                "type": "bind",
                "source": "/config/scripts/" + filename,
                "target": "/" + filename,
                "read_only": True,
            }
        ]
    for role, dependency in {
        "runtime-login": "initialize",
        "provision": "runtime-login",
        "runtime-ready": "provision",
        "web": "runtime-ready",
        "worker": "runtime-ready",
    }.items():
        services[role]["depends_on"] = {
            dependency: {"condition": "service_completed_successfully"}
        }
    return value


@pytest.mark.parametrize(
    "role", ["runtime-login", "provision", "runtime-ready", "web", "worker"]
)
def test_runtime_gate_cannot_be_skipped_or_replaced_by_service_started(role):
    value = runtime_config()
    dependency = next(iter(value["services"][role]["depends_on"]))
    value["services"][role]["depends_on"][dependency]["condition"] = "service_started"
    assert check(value).returncode == 1


@pytest.mark.parametrize(
    "role,key,value",
    [
        ("runtime-ready", "command", ["true"]),
        ("runtime-ready", "entrypoint", ["true"]),
        ("provision", "entrypoint", ["true"]),
        ("runtime-login", "entrypoint", ["true"]),
        ("runtime-login", "command", ["true"]),
        ("runtime-login", "command", ["echo $$RUNTIME_PASSWORD"]),
        ("runtime-login", "user", "root"),
    ],
)
def test_verification_gate_cannot_be_replaced_with_an_unchecked_command(
    role, key, value
):
    candidate = runtime_config()
    candidate["services"][role][key] = value
    assert check(candidate).returncode == 1


def assessment_config():
    value = config()
    web, worker = (value["services"][key] for key in ("web", "worker"))
    web["environment"].update(
        LIBRARIUM_DIRECT_LIBRARY_ROOT="/library",
        LIBRARIUM_CATALOGUE_DIR="/catalogue",
        LIBRARIUM_ARTIFACT_DIR="/artifacts",
    )
    worker["environment"] = dict(web["environment"])
    web["volumes"].extend(
        [
            {
                "source": "/books/synthetic-library",
                "target": "/library",
                "type": "bind",
                "read_only": True,
            },
            {
                "source": "/appdata/librarium-beta/artifacts",
                "target": "/artifacts",
                "type": "bind",
            },
        ]
    )
    worker["volumes"] = copy.deepcopy(web["volumes"])
    return value


def trust_config(value=None):
    value = value or config()
    for role in ("web", "worker"):
        service = value["services"][role]
        service["environment"] = dict(
            service["environment"],
            LIBRARIUM_CONTENT_TRUST_REGISTRY="/content-trust/registry.json",
            LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256="e" * 64,
        )
        service["volumes"].append(
            {
                "source": "/curated/librarium-references",
                "target": "/content-trust",
                "type": "bind",
                "read_only": True,
            }
        )
    return value


def test_assessment_worker_explicitly_shares_read_only_library_catalogue_and_artifacts():
    result = check(assessment_config())
    assert result.returncode == 0, result.stderr


def test_opted_in_catalogue_sync_only_grants_worker_catalogue_write_access():
    value = assessment_config()
    worker = value["services"]["worker"]
    worker["environment"]["LIBRARIUM_CATALOGUE_SYNC_ENABLED"] = "true"
    worker["environment"]["LIBRARIUM_CATALOGUE_STATUS_URL"] = (
        "https://catalogue.example"
    )
    next(m for m in worker["volumes"] if m["target"] == "/catalogue")["read_only"] = (
        False
    )
    result = check(value)
    assert result.returncode == 0, result.stderr
    worker["networks"] = {"default": {}, "catalogue-sync": {}}
    value["networks"]["catalogue-sync"] = {"driver": "bridge", "internal": False}
    assert check(value).returncode == 1
    value["services"]["worker"]["networks"] = {"default": {}}
    leaked = copy.deepcopy(value)
    leaked["services"]["web"]["networks"]["catalogue-sync"] = {}
    assert check(leaked).returncode == 1
    for role, target in (("web", "/catalogue"), ("worker", "/library")):
        changed = copy.deepcopy(value)
        next(m for m in changed["services"][role]["volumes"] if m["target"] == target)[
            "read_only"
        ] = False
        assert check(changed).returncode == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "unconfigured",
        "library_writable",
        "catalogue_writable",
        "foreign_library",
        "missing_catalogue",
        "foreign_artifacts",
    ],
)
def test_assessment_worker_cannot_gain_unbound_or_writable_source_mounts(mutation):
    value = assessment_config()
    worker = value["services"]["worker"]
    if mutation == "unconfigured":
        worker["environment"].pop("LIBRARIUM_DIRECT_LIBRARY_ROOT")
    elif mutation == "missing_catalogue":
        worker["volumes"] = [
            m for m in worker["volumes"] if m["target"] != "/catalogue"
        ]
    else:
        target = (
            "/artifacts"
            if mutation == "foreign_artifacts"
            else "/catalogue"
            if mutation == "catalogue_writable"
            else "/library"
        )
        mount = next(m for m in worker["volumes"] if m["target"] == target)
        if mutation.endswith("writable"):
            mount["read_only"] = False
        else:
            mount["source"] += "/other"
    assert check(value).returncode == 1


def test_curated_reference_mount_requires_explicit_equal_pins_and_read_only_roles():
    result = check(trust_config(assessment_config()))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_pin",
        "bad_pin",
        "different_pin",
        "missing_mount",
        "unconfigured_mount",
        "writable",
        "different_source",
        "artifact_overlap",
        "library_overlap",
        "initialize_mount",
    ],
)
def test_curated_reference_store_cannot_be_writable_aliased_or_self_selected(mutation):
    value = trust_config(assessment_config())
    web, worker = (value["services"][key] for key in ("web", "worker"))
    mount = next(m for m in worker["volumes"] if m["target"] == "/content-trust")
    if mutation == "missing_pin":
        web["environment"].pop("LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256")
    elif mutation == "bad_pin":
        web["environment"]["LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256"] = "untrusted"
    elif mutation == "different_pin":
        worker["environment"]["LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256"] = "f" * 64
    elif mutation == "missing_mount":
        worker["volumes"].remove(mount)
    elif mutation == "unconfigured_mount":
        for role in (web, worker):
            role["environment"].pop("LIBRARIUM_CONTENT_TRUST_REGISTRY")
            role["environment"].pop("LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256")
    elif mutation == "writable":
        mount["read_only"] = False
    elif mutation == "different_source":
        mount["source"] += "/other"
    elif mutation in {"artifact_overlap", "library_overlap"}:
        source = (
            "/appdata/librarium-beta/artifacts/references"
            if mutation == "artifact_overlap"
            else "/books/synthetic-library/references"
        )
        for role in (web, worker):
            next(m for m in role["volumes"] if m["target"] == "/content-trust")[
                "source"
            ] = source
    else:
        value["services"]["initialize"]["volumes"] = [copy.deepcopy(mount)]
    assert check(value).returncode == 1


@pytest.mark.parametrize(
    "unsafe", ["", "writable", "worker", "wrong-root", "artifact-overlap"]
)
def test_native_library_mount_is_opt_in_read_only_and_web_only(unsafe):
    value = config()
    web = value["services"]["web"]
    web["environment"] = {
        **web["environment"],
        "LIBRARIUM_DIRECT_LIBRARY_ROOT": "/library",
    }
    mount = {
        "source": "/Books/CalibreLibrary",
        "target": "/library",
        "type": "bind",
        "read_only": True,
    }
    web["volumes"].append(mount)
    if unsafe == "writable":
        mount["read_only"] = False
    elif unsafe == "worker":
        value["services"]["worker"]["volumes"].append(mount)
    elif unsafe == "wrong-root":
        web["environment"]["LIBRARIUM_DIRECT_LIBRARY_ROOT"] = "/other"
    elif unsafe == "artifact-overlap":
        web["volumes"].append(
            {
                "source": "/Books/CalibreLibrary/artifacts",
                "target": "/artifacts",
                "type": "bind",
            }
        )
    result = check(value)
    assert result.returncode == (1 if unsafe else 0), result.stderr


@pytest.mark.parametrize(
    "change",
    [
        "tag",
        "build",
        "pull-build",
        "ports",
        "alias",
        "writable-catalogue",
        "writer-mount",
    ],
)
def test_refuses_unsafe_runtime(change):
    value = config()
    web = value["services"]["web"]
    if change == "tag":
        web["image"] = "ghcr.io/jshauns81/librarium-public:beta"
    if change == "build":
        web["build"] = {"context": "."}
    if change == "pull-build":
        web["pull_policy"] = "build"
    if change == "ports":
        web["ports"] = ["8123:8123"]
    if change == "alias":
        web["networks"]["edge"]["aliases"] = ["librarium-web"]
    if change == "writable-catalogue":
        web["volumes"][0]["read_only"] = False
    if change == "writer-mount":
        web["volumes"].append({"source": "/books", "target": "/books", "type": "bind"})
    result = check(value)
    assert result.returncode == 1
    assert "configuration refused" in result.stderr


@pytest.mark.parametrize(
    "shared",
    [
        "state",
        "nested-state",
        "network",
        "secret",
        "database-password",
        "origin",
        "project",
    ],
)
def test_refuses_production_overlap(tmp_path, shared):
    beta = config()
    prod = copy.deepcopy(config("librarium"))
    prod["services"]["web"]["environment"] = dict(
        prod["services"]["web"]["environment"],
        LIBRARIUM_SECRET_KEY="prod-" + "y" * 60,
        PGPASSWORD="prod-password",
        LIBRARIUM_PUBLIC_ORIGIN="https://lib.example.org",
    )
    if shared == "state":
        beta["services"]["db"]["volumes"] = prod["services"]["db"]["volumes"]
    if shared == "nested-state":
        beta["services"]["db"]["volumes"][0]["source"] = (
            "/appdata/librarium/postgres/subdir"
        )
    if shared == "network":
        beta["networks"]["edge"]["name"] = prod["networks"]["edge"]["name"]
    if shared == "secret":
        beta["services"]["web"]["environment"]["LIBRARIUM_SECRET_KEY"] = (
            "prod-" + "y" * 60
        )
    if shared == "database-password":
        beta["services"]["web"]["environment"]["PGPASSWORD"] = "prod-password"
    if shared == "origin":
        beta["services"]["web"]["environment"]["LIBRARIUM_PUBLIC_ORIGIN"] = (
            "https://lib.example.org"
        )
    if shared == "project":
        beta["name"] = prod["name"]
    result = check(beta, prod, tmp_path)
    assert result.returncode == 1
    assert "configuration refused" in result.stderr


def test_refuses_host_network_override():
    value = config()
    value["services"]["worker"]["network_mode"] = "host"
    result = check(value)
    assert result.returncode == 1
    assert "configuration refused" in result.stderr


def test_refuses_dot_path_overlap(tmp_path):
    beta = config()
    beta["services"]["db"]["volumes"][0]["source"] = (
        "/appdata/librarium-beta/../librarium/postgres"
    )
    result = check(beta)
    assert result.returncode == 1
    assert "configuration refused" in result.stderr


def test_refuses_worker_edge_network():
    value = config()
    value["services"]["worker"]["networks"] = {"default": {}, "edge": {}}
    result = check(value)
    assert result.returncode == 1
    assert "configuration refused" in result.stderr


def relay_config(tmp_path, *, provisioned=False):
    value = runtime_config() if provisioned else assessment_config()
    cfg = tmp_path / "relay.cfg"
    cfg.write_text("""global
  maxconn 32
  nbthread 1

defaults
  mode tcp
  timeout connect 3s
  timeout client 15s
  timeout server 15s

listen catalogue_api
  bind :12404
  server blc catalogue.example:12404 check inter 30s fall 2 rise 1
""")
    cfg.chmod(0o444)
    value["configs"] = {"catalogue-relay": {"file": str(cfg)}}
    value["networks"]["catalogue-egress"] = {"driver": "bridge", "internal": False}
    value["services"]["catalogue-relay"] = {
        "image": "docker.io/library/haproxy@sha256:1c3568e520453cc8ba98c39501febcf450429c80e6cc27ecad779961d76e597c",
        "entrypoint": ["haproxy"],
        "command": ["-W", "-db", "-f", "/usr/local/etc/haproxy/haproxy.cfg"],
        "user": "99:99",
        "read_only": True,
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "mem_limit": 67108864,
        "pids_limit": 32,
        "cpus": 0.25,
        "restart": "unless-stopped",
        "configs": [
            {
                "source": "catalogue-relay",
                "target": "/usr/local/etc/haproxy/haproxy.cfg",
                "mode": 292,
            }
        ],
        "networks": {"default": {}, "catalogue-egress": {}},
    }
    for role in ("web", "worker"):
        value["services"][role]["environment"]["LIBRARIUM_CATALOGUE_STATUS_URL"] = (
            "http://catalogue-relay:12404"
        )
    worker = value["services"]["worker"]
    worker["environment"]["LIBRARIUM_CATALOGUE_SYNC_ENABLED"] = "true"
    next(m for m in worker["volumes"] if m["target"] == "/catalogue")["read_only"] = (
        False
    )
    return value, cfg


@pytest.mark.parametrize("provisioned", [False, True])
def test_hardened_fixed_upstream_relay_is_admitted(tmp_path, provisioned):
    value, _cfg = relay_config(tmp_path, provisioned=provisioned)
    result = check(value)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "key,bad",
    [
        ("image", IMAGE),
        ("image", "haproxy:latest"),
        ("ports", ["12404:12404"]),
        ("cap_add", ["NET_ADMIN"]),
        ("cap_drop", []),
        ("read_only", False),
        ("security_opt", []),
        ("user", "0:0"),
        ("privileged", True),
        ("entrypoint", ["sh", "-c"]),
        ("command", ["-f", "/other.cfg"]),
        ("mem_limit", 0),
        ("pids_limit", -1),
        ("cpus", 0),
        ("volumes", [{"type": "bind", "source": "/etc", "target": "/host"}]),
        ("environment", {"HAPROXY_EXTRA": "untrusted"}),
    ],
)
def test_relay_hardening_cannot_be_relaxed(tmp_path, key, bad):
    value, _cfg = relay_config(tmp_path)
    value["services"]["catalogue-relay"][key] = bad
    assert check(value).returncode == 1


@pytest.mark.parametrize("role", ["worker", "web", "db", "initialize"])
@pytest.mark.parametrize("network", ["catalogue-egress", "catalogue-sync"])
def test_ordinary_roles_cannot_join_catalogue_egress(tmp_path, role, network):
    value, _cfg = relay_config(tmp_path)
    value["services"][role].setdefault("networks", {"default": {}})[network] = {}
    value["networks"].setdefault(network, {"driver": "bridge"})
    assert check(value).returncode == 1


@pytest.mark.parametrize(
    "directive",
    [
        "  server other other.example:8080 check",
        "  bind :8080",
        "  mode http",
        "  http-request set-dst var(txn.dst)",
        "  stats socket /tmp/admin",
        "resolvers dynamic",
        "  server-template dynamic 10 other.example:8080",
    ],
)
def test_relay_extra_upstreams_and_dynamic_configuration_are_refused(
    tmp_path, directive
):
    value, cfg = relay_config(tmp_path)
    cfg.chmod(0o644)
    cfg.write_text(cfg.read_text() + directive + "\n")
    cfg.chmod(0o444)
    assert check(value).returncode == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "writable_mode",
        "extra_mount",
        "external_network",
        "wrong_url",
        "writable_source",
    ],
)
def test_relay_requires_its_read_only_config_and_fixed_route(tmp_path, mutation):
    value, cfg = relay_config(tmp_path)
    relay = value["services"]["catalogue-relay"]
    if mutation == "missing":
        cfg.unlink()
    elif mutation == "writable_mode":
        relay["configs"][0]["mode"] = 0o644
    elif mutation == "extra_mount":
        relay["configs"].append(dict(relay["configs"][0], target="/extra.cfg"))
    elif mutation == "external_network":
        value["networks"]["catalogue-egress"]["external"] = True
    elif mutation == "wrong_url":
        value["services"]["worker"]["environment"]["LIBRARIUM_CATALOGUE_STATUS_URL"] = (
            "http://other.example"
        )
    else:
        cfg.chmod(0o644)
    assert check(value).returncode == 1


@pytest.mark.parametrize(
    "key,bad",
    [
        ("post_start", [{"command": "sh", "user": "root"}]),
        ("healthcheck", {"test": ["CMD-SHELL", "sh -c true"]}),
        ("volumes_from", ["worker"]),
    ],
)
def test_relay_cannot_add_execution_or_mount_overrides(tmp_path, key, bad):
    value, _cfg = relay_config(tmp_path)
    value["services"]["catalogue-relay"][key] = bad
    assert check(value).returncode == 1


def test_compose_string_resource_and_octal_config_modes_are_admitted(tmp_path):
    value, _cfg = relay_config(tmp_path)
    relay = value["services"]["catalogue-relay"]
    relay["mem_limit"] = "67108864"
    relay["configs"][0]["mode"] = "0444"
    result = check(value)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("forwarded", ["192.0.2.10", "192.0.2.10,2001:db8::10"])
def test_forwarding_trust_may_name_only_operator_proxies(forwarded):
    value = copy.deepcopy(config())
    value["services"]["web"]["environment"] = {
        **value["services"]["web"]["environment"],
        "LIBRARIUM_OPERATOR_PROXY_IPS": "192.0.2.10,2001:db8::10",
        "FORWARDED_ALLOW_IPS": forwarded,
    }
    validate_config(value)


@pytest.mark.parametrize("forwarded", ["*", "", "192.0.2.11", "192.0.2.0/24", "proxy.example.org",
                                       "192.0.2.10,*"])
def test_forwarding_trust_cannot_widen_beyond_operator_proxies(forwarded):
    value = copy.deepcopy(config())
    value["services"]["web"]["environment"] = {
        **value["services"]["web"]["environment"],
        "LIBRARIUM_OPERATOR_PROXY_IPS": "192.0.2.10",
        "FORWARDED_ALLOW_IPS": forwarded,
    }
    with pytest.raises(ValueError, match="forwarding trust"):
        validate_config(value)


@pytest.mark.parametrize("role,peers", [("web", None), ("worker", None)])
def test_forwarding_trust_requires_web_operator_identity(role, peers):
    value = copy.deepcopy(runtime_config())
    value["services"][role]["environment"] = {
        **value["services"][role]["environment"], "FORWARDED_ALLOW_IPS": "192.0.2.10",
    }
    with pytest.raises(ValueError, match="forwarding trust"):
        validate_config(value)


def test_optional_google_key_is_admitted_only_on_cover_role():
    value = cover_sources_config()
    value["services"]["cover-sources"]["environment"]["GOOGLE_BOOKS_API_KEY"] = "fixture-key"
    assert check(value).returncode == 0
    for role in ("web", "worker", "db"):
        unsafe = copy.deepcopy(value)
        unsafe["services"][role]["environment"]["GOOGLE_BOOKS_API_KEY"] = "fixture-key"
        assert check(unsafe).returncode != 0


@pytest.mark.parametrize("key", ["kéy", "key\nwith-newline", "key with space", "key\x00"])
def test_google_key_must_be_printable_ascii_token(key):
    value = cover_sources_config()
    value["services"]["cover-sources"]["environment"]["GOOGLE_BOOKS_API_KEY"] = key
    assert check(value).returncode != 0
