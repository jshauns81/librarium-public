"""Check resolved Compose JSON before using a registry image on a target."""

import argparse
import json
import os
import re
import stat
import sys
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

RUNTIME_LOGIN_COMMAND = """if ! psql -X -q --no-password --file=/runtime_login.sql >/dev/null 2>&1; then
  echo 'Runtime login setup refused' >&2
  exit 1
fi
echo 'Runtime login setup completed'
"""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def mounts(service, target):
    return [mount for mount in service.get("volumes", []) if mount["target"] == target]


def overlaps(first, second):
    first, second = Path(first), Path(second)
    return (
        first == second or first.is_relative_to(second) or second.is_relative_to(first)
    )


RELAY_IMAGE = "docker.io/library/haproxy@sha256:1c3568e520453cc8ba98c39501febcf450429c80e6cc27ecad779961d76e597c"
RELAY_PATH = "/usr/local/etc/haproxy/haproxy.cfg"
RELAY_PREFIX = [
    "global",
    "maxconn 32",
    "nbthread 1",
    "defaults",
    "mode tcp",
    "timeout connect 3s",
    "timeout client 15s",
    "timeout server 15s",
    "listen catalogue_api",
    "bind :12404",
]


def check_relay(value):
    relay = value["services"]["catalogue-relay"]
    require(
        set(relay)
        <= {
            "image",
            "entrypoint",
            "command",
            "user",
            "read_only",
            "security_opt",
            "cap_drop",
            "mem_limit",
            "pids_limit",
            "cpus",
            "restart",
            "configs",
            "networks",
            "healthcheck",
        },
        "unexpected relay override",
    )
    if "healthcheck" in relay:
        require(
            relay["healthcheck"]
            == {
                "test": ["CMD", "haproxy", "-c", "-q", "-f", RELAY_PATH],
                "interval": "30s",
                "timeout": "3s",
                "retries": 3,
            },
            "config-only relay healthcheck required",
        )
    require(
        relay.get("image") == RELAY_IMAGE
        and relay.get("entrypoint") == ["haproxy"]
        and relay.get("command") == ["-W", "-db", "-f", RELAY_PATH],
        "pinned fixed relay execution required",
    )
    require(
        relay.get("user") == "99:99"
        and relay.get("read_only") is True
        and relay.get("cap_drop") == ["ALL"]
        and relay.get("security_opt") == ["no-new-privileges:true"]
        and not any(
            relay.get(key)
            for key in (
                "cap_add",
                "ports",
                "privileged",
                "volumes",
                "tmpfs",
                "devices",
                "environment",
                "env_file",
                "sysctls",
                "use_api_socket",
            )
        ),
        "read-only unprivileged relay required",
    )
    require(
        relay.get("mem_limit") in {"64m", "67108864", 64 * 1024 * 1024}
        and relay.get("pids_limit") == 32
        and float(relay.get("cpus", 0)) == 0.25
        and relay.get("restart") == "unless-stopped",
        "bounded relay resources required",
    )
    network = value["networks"].get("catalogue-egress", {})
    require(
        network.get("driver", "bridge") == "bridge"
        and not network.get("internal", False)
        and not network.get("external", False)
        and not network.get("driver_opts"),
        "dedicated relay egress bridge required",
    )
    configs = relay.get("configs", [])
    require(
        len(configs) == 1
        and configs[0]
        == {
            "source": "catalogue-relay",
            "target": RELAY_PATH,
            "mode": configs[0].get("mode"),
        }
        and configs[0]["mode"] in {0o444, "0444"},
        "one read-only relay configuration required",
    )
    config = value.get("configs", {}).get("catalogue-relay", {})
    require(
        set(config) <= {"file", "name"} and config.get("file"),
        "relay config file required",
    )
    path = Path(config["file"])
    require(path.is_absolute(), "absolute relay configuration required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_size <= 4096
            and not info.st_mode & 0o222,
            "small read-only relay configuration required",
        )
        lines = [
            " ".join(line.split())
            for line in stream.read(4097).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    require(lines[:-1] == RELAY_PREFIX, "fixed TCP relay configuration required")
    upstream = re.fullmatch(
        r"server blc ([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?):([0-9]{1,5}) check inter 30s fall 2 rise 1",
        lines[-1],
    )
    require(
        upstream and 1 <= int(upstream[2]) <= 65535,
        "one literal relay upstream required",
    )
    for role in ("web", "worker"):
        require(
            value["services"][role]["environment"].get("LIBRARIUM_CATALOGUE_STATUS_URL")
            == "http://catalogue-relay:12404",
            "catalogue reads must use the fixed relay",
        )


def check_cover_sources(value, image):
    services, networks = value["services"], value["networks"]
    source = services["cover-sources"]
    require(
        set(source)
        <= {
            "image",
            "profiles",
            "user",
            "command",
            "entrypoint",
            "environment",
            "read_only",
            "tmpfs",
            "cap_drop",
            "security_opt",
            "init",
            "mem_limit",
            "pids_limit",
            "cpus",
            "restart",
            "networks",
        },
        "unexpected cover source override",
    )
    require(
        source.get("image") == image
        and source.get("profiles") == ["cover-sources"]
        and source.get("command") == ["python", "-m", "librarium.cover_source_server"]
        and source.get("entrypoint") is None
        and source.get("user") == "10001:10001"
        and source.get("read_only") is True
        and source.get("cap_drop") == ["ALL"]
        and source.get("security_opt") == ["no-new-privileges:true"]
        and source.get("init") is True
        and source.get("tmpfs") == ["/tmp:size=32m,mode=1777"],
        "fixed unprivileged cover source execution required",
    )
    require(
        source.get("mem_limit") in {"512m", "536870912", 512 * 1024 * 1024}
        and source.get("pids_limit") == 32
        and float(source.get("cpus", 0)) == 1
        and source.get("restart") == "unless-stopped",
        "bounded cover source resources required",
    )
    for name in ("default", "edge", "cover-control", "cover-egress"):
        network = networks[name]
        require(
            network.get("internal", False) is (name != "cover-egress")
            and network.get("driver", "bridge") == "bridge"
            and not network.get("external", False)
            and not network.get("driver_opts"),
            "dedicated cover source bridges required",
        )
    require(
        source["networks"]["cover-control"].get("aliases")
        == ["cover-control-listener"],
        "fixed cover control listener required",
    )
    source_env = source.get("environment", {})
    secret_key = "LIBRARIUM_COVER_SOURCES_SECRET"
    secret = source_env.get(secret_key)
    require(
        set(source_env) in ({secret_key, "HARDCOVER_TOKEN"}, {secret_key, "HARDCOVER_TOKEN", "GOOGLE_BOOKS_API_KEY"})
        and isinstance(source_env.get("GOOGLE_BOOKS_API_KEY", ""), str)
        and source_env.get("GOOGLE_BOOKS_API_KEY", "").isascii()
        and source_env.get("GOOGLE_BOOKS_API_KEY", "").isprintable()
        and " " not in source_env.get("GOOGLE_BOOKS_API_KEY", "")
        and isinstance(secret, str)
        and len(secret) >= 32
        and secret.isascii()
        and services["worker"]["environment"].get(secret_key) == secret,
        "matching protected cover control secrets required",
    )
    for role, service in services.items():
        if role != "cover-sources":
            require("GOOGLE_BOOKS_API_KEY" not in service.get("environment", {}),
                    "Google key role isolation required")
        if role not in {"worker", "cover-sources"}:
            require(
                secret_key not in service.get("environment", {}),
                "cover secret role isolation required",
            )


def check_source_browser(value):
    services, networks = value["services"], value["networks"]
    role = services["source-browser"]
    require(
        "cover-sources" in services,
        "browser requires the cover-source isolation overlay",
    )
    require(
        set(role)
        <= {
            "image",
            "profiles",
            "user",
            "environment",
            "read_only",
            "tmpfs",
            "volumes",
            "cap_drop",
            "security_opt",
            "init",
            "mem_limit",
            "pids_limit",
            "cpus",
            "restart",
            "networks",
            "command",
            "entrypoint",
        },
        "unexpected browser override",
    )
    require(
        re.fullmatch(
            r"ghcr.io/jshauns81/librarium-source-browser@sha256:[0-9a-f]{64}",
            role.get("image", ""),
        )
        and role.get("profiles") == ["source-browser"]
        and role.get("user") == "999:999"
        and role.get("read_only") is True
        and role.get("cap_drop") == ["ALL"]
        and role.get("security_opt")
        == ["no-new-privileges:true", "seccomp:./services/source-browser/seccomp.json"]
        and role.get("init") is True
        and role.get("tmpfs") == ["/tmp:rw,nosuid,nodev,size=256m,mode=1777"]
        and role.get("mem_limit") in {"2g", "2147483648", 2 * 1024**3}
        and role.get("pids_limit") == 256
        and float(role.get("cpus", 0)) == 2
        and role.get("restart") == "unless-stopped"
        and role.get("command") is None
        and role.get("entrypoint") is None,
        "fixed sandboxed browser execution required",
    )
    network = networks["source-browser-control"]
    require(
        network.get("internal") is True
        and network.get("driver", "bridge") == "bridge"
        and not network.get("external")
        and not network.get("driver_opts"),
        "private browser control bridge required",
    )
    require(
        role["networks"]["source-browser-control"].get("aliases")
        == ["source-browser-control-listener"],
        "fixed browser control listener required",
    )
    secret_key = "LIBRARIUM_SOURCE_BROWSER_SECRET"
    env = role.get("environment", {})
    secret = env.get(secret_key)
    require(
        set(env) == {secret_key}
        and isinstance(secret, str)
        and len(secret) >= 32
        and secret.isascii()
        and not any(ord(c) <= 32 for c in secret)
        and services["worker"]["environment"].get(secret_key) == secret,
        "matching browser-only key required",
    )
    require(
        secret
        != services["cover-sources"]["environment"].get(
            "LIBRARIUM_COVER_SOURCES_SECRET"
        ),
        "separate browser request key required",
    )
    for name, service in services.items():
        if name not in {"worker", "source-browser"}:
            require(
                secret_key not in service.get("environment", {}),
                "browser key role isolation required",
            )
    volume = value.get("volumes", {}).get("source-browser-profile", {})
    require(
        volume == {"name": value["name"] + "_source-browser-profile"},
        "dedicated browser profile volume required",
    )
    require(
        role.get("volumes")
        == [
            {
                "type": "volume",
                "source": "source-browser-profile",
                "target": "/data",
                "volume": {},
            }
        ],
        "only the owned browser profile may be mounted",
    )


def check(value: dict, production: dict | None = None) -> None:
    services = value["services"]
    base_roles = {"db", "initialize", "web", "worker"}
    helper_roles = {"runtime-login", "provision", "runtime-ready"}
    app_roles = set(services) - {"catalogue-relay", "cover-sources", "source-browser"}
    provisioned = app_roles == base_roles | helper_roles
    require(
        app_roles == base_roles or provisioned,
        "unexpected service roles",
    )
    image = services["web"]["image"]
    require(
        re.fullmatch("ghcr.io/jshauns81/librarium@sha256:[0-9a-f]{64}", image),
        "digest required",
    )
    name = value["name"]
    require(
        re.fullmatch("librarium-[a-z0-9-]+", name), "dedicated project name required"
    )
    networks = value["networks"]
    require(networks["default"]["internal"], "private database network required")
    env = services["web"]["environment"]
    origin = urlsplit(env["LIBRARIUM_PUBLIC_ORIGIN"])
    require(
        origin.scheme == "https" and origin.hostname and (not origin.path),
        "HTTPS origin required",
    )
    require(
        not origin.username
        and (not origin.password)
        and (not origin.query)
        and (not origin.fragment),
        "invalid config",
    )
    require(env["LIBRARIUM_TRUST_PROXY"] == "1", "trusted proxy required")
    for role, service in services.items():
        identity_keys = {
            key
            for key in service.get("environment", {})
            if key.startswith("LIBRARIUM_OPERATOR_")
        }
        require(
            not identity_keys
            or (role == "web" and identity_keys == {"LIBRARIUM_OPERATOR_PROXY_IPS"}),
            "operator identity configuration is web-only with one fixed header",
        )
        if identity_keys:
            peers = service["environment"]["LIBRARIUM_OPERATOR_PROXY_IPS"]
            try:
                require(
                    isinstance(peers, str) and "%" not in peers,
                    "operator identity requires literal proxy IP addresses",
                )
                if peers:
                    for peer in peers.split(","):
                        ip_address(peer.strip())
            except ValueError:
                raise ValueError(
                    "operator identity requires literal proxy IP addresses"
                ) from None
        forwarded = service.get("environment", {}).get("FORWARDED_ALLOW_IPS")
        if forwarded is not None:
            require(role == "web" and bool(identity_keys), "forwarding trust is web-only")
            trusted = service["environment"]["LIBRARIUM_OPERATOR_PROXY_IPS"]
            try:
                require(
                    isinstance(forwarded, str)
                    and bool(forwarded)
                    and "%" not in forwarded
                    and {ip_address(v.strip()) for v in forwarded.split(",")}
                    <= {ip_address(v.strip()) for v in trusted.split(",") if trusted},
                    "forwarding trust must name only the operator proxy addresses",
                )
            except ValueError:
                raise ValueError(
                    "forwarding trust must name only the operator proxy addresses"
                ) from None
        require(
            not any(
                key in service.get("environment", {})
                for key in (
                    "LIBRARIUM_RUNTIME_DB_USER",
                    "LIBRARIUM_RUNTIME_DB_PASSWORD",
                )
            ),
            "shadowed database configuration forbidden",
        )
        require(not service.get("network_mode"), "network mode overrides forbidden")
        sync_enabled = str(
            service.get("environment", {}).get("LIBRARIUM_CATALOGUE_SYNC_ENABLED", "")
        ).lower() in {"true", "1"}
        expected_networks = {"default", "edge"} if role == "web" else {"default"}
        if role == "catalogue-relay":
            expected_networks = {"default", "catalogue-egress"}
        if "cover-sources" in services and role == "worker":
            expected_networks = {"default", "cover-control"}
            if "source-browser" in services:
                expected_networks.add("source-browser-control")
        if role == "cover-sources":
            expected_networks = {"cover-control", "cover-egress"}
        if role == "source-browser":
            expected_networks = {"source-browser-control", "cover-egress"}
        require(
            set(service.get("networks", {"default": {}})) == expected_networks,
            "role network isolation required",
        )
        require(
            not service.get("build") and service.get("pull_policy") != "build",
            "build forbidden",
        )
        require(
            not service.get("ports") and (not service.get("privileged")),
            "private services required",
        )
        if role not in {
            "db",
            "runtime-login",
            "catalogue-relay",
            "cover-sources",
            "source-browser",
        }:
            require(service["image"] == image, "all app roles must share one digest")
            for key in [
                "LIBRARIUM_SECRET_KEY",
                "LIBRARIUM_PUBLIC_ORIGIN",
            ]:
                require(
                    service["environment"][key] == env[key],
                    "app role configuration mismatch",
                )
        allowed = {
            "source-browser": {"/data"},
            "cover-sources": set(),
            "catalogue-relay": set(),
            "db": {"/var/lib/postgresql"},
            "initialize": set(),
            "provision": set(),
            "runtime-login": {"/runtime_login.sql"},
            "runtime-ready": {"/runtime_identity.py"},
            "web": {"/catalogue", "/artifacts", "/library", "/content-trust"},
            "worker": {"/artifacts", "/catalogue", "/library", "/content-trust"},
        }[role]
        for mount in service.get("volumes", []):
            if role == "source-browser":
                continue  # check_source_browser verifies the complete named-volume shape.
            require(
                mount["type"] == "bind" and mount["target"] in allowed,
                "unexpected data mount",
            )
            require(
                Path(mount["source"]).is_absolute(), "absolute state paths required"
            )
            require(
                all(
                    part not in {"", ".", ".."}
                    for part in mount["source"].split("/")[1:]
                ),
                "canonical state paths required",
            )
            sync_writer = (
                role == "worker"
                and mount["target"] == "/catalogue"
                and sync_enabled
                and bool(service["environment"].get("LIBRARIUM_CATALOGUE_STATUS_URL"))
            )
            if (
                mount["target"] in {"/catalogue", "/library", "/content-trust"}
                and not sync_writer
            ):
                require(mount.get("read_only"), "source inputs must be read-only")
            if mount["target"] == "/library":
                require(
                    env.get("LIBRARIUM_DIRECT_LIBRARY_ROOT") == "/library",
                    "library mount requires the native reader",
                )
            if role in {"runtime-login", "runtime-ready"}:
                require(
                    mount.get("read_only")
                    and Path(mount["source"]).name == mount["target"].lstrip("/"),
                    "bootstrap source must be a read-only pinned configuration file",
                )
    if "catalogue-relay" in services:
        check_relay(value)
    if "cover-sources" in services:
        check_cover_sources(value, image)
    if "source-browser" in services:
        check_source_browser(value)
    web, worker = services["web"], services["worker"]
    worker_env = worker["environment"]
    owner_env = services["initialize"]["environment"]
    require(
        isinstance(env.get("PGPASSWORD"), str)
        and bool(env["PGPASSWORD"])
        and worker_env.get("PGPASSWORD") == env["PGPASSWORD"],
        "runtime database credentials must match",
    )
    users = [
        service["environment"].get("PGUSER")
        for service in (web, worker, services["initialize"])
    ]
    require(
        all(isinstance(user, str) and bool(user) for user in users)
        and users[0] == users[1],
        "explicit matching runtime logins required",
    )
    database_env = services["db"]["environment"]
    require(
        all(
            isinstance(database_env.get(key), str) and bool(database_env[key])
            for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        )
        and owner_env["PGUSER"] == database_env["POSTGRES_USER"]
        and owner_env["PGPASSWORD"] == database_env["POSTGRES_PASSWORD"],
        "owner credentials must bind the selected database",
    )
    for role_env in (env, worker_env, owner_env):
        require(
            role_env.get("PGHOST") == "db"
            and str(role_env.get("PGPORT")) == "5432"
            and role_env.get("PGDATABASE") == database_env["POSTGRES_DB"],
            "owner and runtime must use the selected database",
        )
    if users[0] != users[2]:
        require(
            provisioned,
            "split runtime requires completed provisioning gates",
        )
        require(
            owner_env["PGPASSWORD"] != env["PGPASSWORD"],
            "separate owner credentials required",
        )
    else:
        require(
            not provisioned and owner_env.get("PGPASSWORD") == env["PGPASSWORD"],
            "shared login requires matching credentials",
        )
    if provisioned:
        login, grant, ready = (
            services[key] for key in ("runtime-login", "provision", "runtime-ready")
        )
        require(
            login["image"] == services["db"]["image"],
            "bootstrap database image must match",
        )
        require(
            login["environment"].get("RUNTIME_PASSWORD") == env["PGPASSWORD"],
            "bootstrap runtime password must match",
        )
        for service in (login, grant, ready):
            selected = service["environment"]
            expected_env = env if service is ready else owner_env
            require(
                all(
                    selected.get(key) == expected_env[key]
                    for key in (
                        "PGHOST",
                        "PGPORT",
                        "PGDATABASE",
                        "PGUSER",
                        "PGPASSWORD",
                    )
                ),
                "bootstrap database bindings must match",
            )
            require(
                service.get("read_only")
                and service.get("cap_drop") == ["ALL"]
                and "no-new-privileges:true" in service.get("security_opt", [])
                and service.get("restart", "no") == "no",
                "bootstrap roles must be bounded one-shot services",
            )
        edges = {
            "runtime-login": "initialize",
            "provision": "runtime-login",
            "runtime-ready": "provision",
            "web": "runtime-ready",
            "worker": "runtime-ready",
        }
        for dependent, prerequisite in edges.items():
            require(
                services[dependent]
                .get("depends_on", {})
                .get(prerequisite, {})
                .get("condition")
                == "service_completed_successfully",
                "runtime admission requires completed bootstrap gates",
            )
        require(
            grant.get("command")
            == ["python", "manage.py", "provision_runtime_role", "librarium_runtime"]
            and env["PGUSER"] == "librarium_runtime",
            "existing runtime grant owner required",
        )
        require(
            ready.get("command")
            == [
                "python",
                "-c",
                "exec(compile(open('/runtime_identity.py').read(), '/runtime_identity.py', 'exec'))",
            ]
            and not ready.get("entrypoint")
            and not grant.get("entrypoint")
            and login.get("entrypoint") == ["/bin/sh", "-ec"]
            and login.get("command") == [RUNTIME_LOGIN_COMMAND]
            and login.get("user") == "postgres",
            "runtime verification execution contract required",
        )
        for role, target in (
            ("runtime-login", "/runtime_login.sql"),
            ("runtime-ready", "/runtime_identity.py"),
        ):
            require(
                len(mounts(services[role], target)) == 1,
                "bootstrap configuration mount required",
            )
    assessment_inputs = mounts(worker, "/library") + mounts(worker, "/catalogue")
    if assessment_inputs or worker_env.get("LIBRARIUM_DIRECT_LIBRARY_ROOT"):
        for key, target in (
            ("LIBRARIUM_DIRECT_LIBRARY_ROOT", "/library"),
            ("LIBRARIUM_CATALOGUE_DIR", "/catalogue"),
            ("LIBRARIUM_ARTIFACT_DIR", "/artifacts"),
        ):
            require(
                env.get(key) == worker_env.get(key) == target,
                "explicit assessment input configuration required",
            )
            selected, observed = mounts(web, target), mounts(worker, target)
            require(
                len(selected) == len(observed) == 1
                and selected[0]["source"] == observed[0]["source"],
                "assessment roles require identical selected mounts",
            )
            if target == "/artifacts":
                require(
                    not selected[0].get("read_only")
                    and not observed[0].get("read_only"),
                    "assessment artifacts must remain writable",
                )
    trust_keys = (
        "LIBRARIUM_CONTENT_TRUST_REGISTRY",
        "LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256",
    )
    trust_selected = any(
        service.get("environment", {}).get(key) or mounts(service, "/content-trust")
        for service in services.values()
        for key in trust_keys
    )
    if trust_selected:
        digest = env.get(trust_keys[1], "")
        require(
            isinstance(digest, str) and re.fullmatch("[0-9a-f]{64}", digest),
            "curated registry digest required",
        )
        selected = []
        for role in ("web", "worker"):
            service = services[role]
            require(
                service["environment"].get(trust_keys[0])
                == "/content-trust/registry.json"
                and service["environment"].get(trust_keys[1]) == digest,
                "curated reference role pins must agree",
            )
            values = mounts(service, "/content-trust")
            require(
                len(values) == 1, "curated registry requires one read-only store mount"
            )
            selected.append(values[0]["source"])
        require(
            selected[0] == selected[1], "curated reference roles must share one store"
        )
        for role in set(services) - {"web", "worker"}:
            require(
                not any(
                    services[role].get("environment", {}).get(key) for key in trust_keys
                ),
                "curated registry is restricted to reading roles",
            )
        for service in services.values():
            for mount in service.get("volumes", []):
                if mount["target"] != "/content-trust":
                    require(
                        not overlaps(selected[0], mount["source"]),
                        "curated references overlap another source or state mount",
                    )
    library_mounts = [
        m for m in services["web"].get("volumes", []) if m["target"] == "/library"
    ]
    if env.get("LIBRARIUM_DIRECT_LIBRARY_ROOT"):
        require(
            len(library_mounts) == 1,
            "native reader requires one read-only library mount",
        )
    for library in library_mounts:
        source = Path(library["source"])
        for service in services.values():
            for mount in service.get("volumes", []):
                if not mount.get("read_only"):
                    writable = Path(mount["source"])
                    require(
                        not (
                            source == writable
                            or source.is_relative_to(writable)
                            or writable.is_relative_to(source)
                        ),
                        "writable state overlaps the authoritative library",
                    )
    aliases = services["web"]["networks"]["edge"]["aliases"]
    require(aliases == [name + "-web"], "environment-specific edge alias required")
    if production:
        require(name != production["name"], "shared Compose project")
        require(
            networks["edge"]["name"] != production["networks"]["edge"]["name"],
            "shared edge network",
        )
        prod_env = production["services"]["web"]["environment"]
        for key in ["LIBRARIUM_SECRET_KEY", "LIBRARIUM_PUBLIC_ORIGIN"]:
            require(
                env[key] != prod_env[key], "shared environment credential or origin"
            )
        candidate_passwords = {env["PGPASSWORD"], owner_env["PGPASSWORD"]}
        production_passwords = {
            service.get("environment", {}).get(key)
            for service in production["services"].values()
            for key in ("PGPASSWORD", "POSTGRES_PASSWORD", "RUNTIME_PASSWORD")
        } - {None, ""}
        require(
            not candidate_passwords.intersection(production_passwords),
            "shared environment database credential",
        )
        prod_mounts = [
            Path(m["source"])
            for s in production["services"].values()
            for m in s.get("volumes", [])
            if not m.get("read_only")
        ]
        for service in services.values():
            for mount in service.get("volumes", []):
                candidate = Path(mount["source"])
                require(
                    not any(
                        candidate == p
                        or candidate.is_relative_to(p)
                        or p.is_relative_to(candidate)
                        for p in prod_mounts
                    ),
                    "production state overlaps beta mounts",
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    try:
        production = json.loads(args.compare.read_text()) if args.compare else None
        check(json.load(sys.stdin), production)
    except (AssertionError, KeyError, ValueError, TypeError, OSError, IndexError):
        parser.exit(
            1, "Registry configuration refused: invalid or overlapping deployment\n"
        )
    print("PASS: registry deployment configuration")


if __name__ == "__main__":
    main()
