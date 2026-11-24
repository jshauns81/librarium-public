"""Retained source registry for offline canonical resolution; no runtime credentials."""

import tomllib
from dataclasses import dataclass
from importlib import resources

DEFAULT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class SourceInfo:
    name: str
    origin_group: str
    priority: int
    stale_days: int
    rps: float
    timeout_s: float = DEFAULT_TIMEOUT_S


def load_sources() -> dict[str, SourceInfo]:
    """Load the source registry from the packaged sources.toml."""
    text = resources.files("bl_catalog").joinpath("sources.toml").read_text(encoding="utf-8")
    raw = tomllib.loads(text)["sources"]
    return {
        name: SourceInfo(
            name=name,
            origin_group=str(entry["origin_group"]),
            priority=int(entry["priority"]),
            stale_days=int(entry["stale_days"]),
            rps=float(entry["rps"]),
            timeout_s=float(entry.get("timeout_s", DEFAULT_TIMEOUT_S)),
        )
        for name, entry in raw.items()
    }
