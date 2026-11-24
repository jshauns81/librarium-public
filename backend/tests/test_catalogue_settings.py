"""Catalogue cover defaults must survive an unchanged example environment."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("override", [None, "", "/replica/custom"])
@pytest.mark.parametrize("root", ["/replica", ""])
def test_cover_directory_environment_defaults(root, override):
    env = dict(
        os.environ,
        LIBRARIUM_CATALOGUE_DIR=root,
        PYTHONPATH=str(Path(__file__).resolve().parents[1]),
    )
    keys = ("LIBRARIUM_CATALOGUE_COVER_DIR", "LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR")
    for key in keys:
        env.pop(key, None)
        if override is not None:
            env[key] = override
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from librarium import settings as s; print(json.dumps([s.LIBRARIUM_CATALOGUE_COVER_DIR, s.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR]))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == [
        override or (root + "/" + variant if root else "") for variant in ("covers", "upscaled")
    ]
