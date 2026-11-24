"""Source-derived package identity; declarations never attest to the running image."""

import ast
import hashlib
import json
import os
import re
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "librarium.build-identity.v1"
SOURCE_SCOPE = "application-source-and-assets.v1"
MAX_IDENTITY_BYTES = 16 * 1024
POLICY_PREFIXES = {
    "inspection_policy": "librarium.epub-structure",
    "validation_policy": "librarium.epub-validation",
}
REQUIRED_CONFIGURATION = [
    "LIBRARIUM_IMAGE",
    "LIBRARIUM_DATA_ROOT",
    "LIBRARIUM_SECRET_KEY",
    "LIBRARIUM_DB_PASSWORD",
    "LIBRARIUM_PUBLIC_ORIGIN",
    "LIBRARIUM_EDGE_NETWORK",
    "LIBRARIUM_PROJECT_NAME",
]


def constant(path: str, name: str, field: str | None = None, *, root: Path = ROOT):
    for node in ast.parse((root / path).read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            value = node.value
            if field is not None and isinstance(value, ast.Dict):
                value = next(
                    v
                    for k, v in zip(value.keys, value.values)
                    if isinstance(k, ast.Constant) and k.value == field
                )
            if value is None:
                raise ValueError("missing compatibility constant")
            return ast.literal_eval(value)
    raise ValueError(f"missing compatibility constant: {name}")


def compatibility(root: Path = ROOT) -> dict:
    migrations = {}
    for path in (root / "backend/librarium/migrations").glob("[0-9]*.py"):
        tree = ast.parse(path.read_text())
        migration = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Migration"
        )
        deps = next(
            n.value
            for n in migration.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "dependencies" for t in n.targets)
        )
        migrations[path.stem] = ast.literal_eval(deps)
    depended_on = {name for deps in migrations.values() for app, name in deps if app == "librarium"}
    return {
        "migration_leaves": sorted(set(migrations) - depended_on),
        "inspection_policy": constant(
            "backend/librarium/epub_inspection.py", "POLICY_VERSION", root=root
        ),
        "validation_policy": constant(
            "backend/librarium/epubcheck_process.py",
            "VALIDATION_POLICY",
            "version",
            root=root,
        ),
        "required_configuration": REQUIRED_CONFIGURATION.copy(),
    }


def current_compatibility() -> dict:
    return compatibility()


def valid_compatibility(value) -> bool:
    if type(value) is not dict or set(value) != {
        "migration_leaves",
        "required_configuration",
        *POLICY_PREFIXES,
    }:
        return False
    leaves = value["migration_leaves"]
    if (
        type(leaves) is not list
        or not 1 <= len(leaves) <= 64
        or any(
            type(v) is not str or not re.fullmatch(r"[0-9]{4}_[a-z0-9_]{1,80}", v) for v in leaves
        )
        or leaves != sorted(set(leaves))
        or value["required_configuration"] != REQUIRED_CONFIGURATION
    ):
        return False
    return all(
        type(value[key]) is str
        and re.fullmatch(re.escape(prefix) + r"\.v[1-9][0-9]{0,5}", value[key]) is not None
        for key, prefix in POLICY_PREFIXES.items()
    )


def valid_identity(value) -> bool:
    return (
        type(value) is dict
        and set(value) == {"schema", "source_scope", "source_sha256", "compatibility"}
        and value["schema"] == SCHEMA
        and value["source_scope"] == SOURCE_SCOPE
        and type(value["source_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"]) is not None
        and valid_compatibility(value["compatibility"])
    )


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def identity_sha256(value: dict) -> str:
    if not valid_identity(value):
        raise ValueError("build identity invalid")
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("build identity invalid")
        result[key] = value
    return result


def _reject(value):
    raise ValueError("build identity invalid")


def load_build_identity(path: Path | None = None) -> dict | None:
    path = Path(path) if path is not None else Path(__file__).with_name("build-identity.json")
    descriptor = None
    try:
        # Opening each directory refuses symlinked parents as well as a symlinked record.
        if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
            return None
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_mode & 0o022
                or not 0 < before.st_size <= MAX_IDENTITY_BYTES
            ):
                return None
            data = stream.read(MAX_IDENTITY_BYTES + 1)
            after = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if len(data) != before.st_size or any(
                getattr(before, f) != getattr(after, f) for f in fields
            ):
                return None
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_reject)
        return value if valid_identity(value) else None
    except OSError, ValueError, TypeError, RecursionError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def build_status(identity: dict | None, declared_digest: str = "") -> dict:
    known = valid_identity(identity)
    runtime_state = "unknown"
    if known and identity:
        try:
            current = current_compatibility()
            if valid_compatibility(current):
                runtime_state = (
                    "compatible" if current == identity["compatibility"] else "incompatible"
                )
        except OSError, ValueError, TypeError, SyntaxError, StopIteration:
            pass
    return {
        "state": "known" if known else "unknown",
        "source_sha256": identity["source_sha256"] if known and identity else None,
        "identity_sha256": identity_sha256(identity) if known and identity else None,
        "compatibility": identity["compatibility"] if known and identity else None,
        "runtime_compatibility_state": runtime_state,
        "declared_image_digest": declared_digest
        if type(declared_digest) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", declared_digest)
        else None,
        "running_image_digest": None,
        "running_image_state": "unknown",
    }
