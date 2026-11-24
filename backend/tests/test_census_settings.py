"""Census capacity follows explicit configuration and a conservative CPU default."""

import runpy

import pytest
from django.core.exceptions import ImproperlyConfigured
from librarium import settings as settings_module


@pytest.mark.parametrize("cpus,expected", [(None, 1), (1, 1), (2, 1), (4, 2), (8, 4), (64, 4)])
def test_default_capacity(monkeypatch, cpus, expected):
    monkeypatch.delenv("LIBRARIUM_CENSUS_CONCURRENCY", raising=False)
    monkeypatch.setattr("os.cpu_count", lambda: cpus)
    assert runpy.run_path(settings_module.__file__)["COVER_CENSUS_OBSERVATION_WORKERS"] == expected


@pytest.mark.parametrize("value", ["1", "2", "8"])
def test_explicit_capacity(monkeypatch, value):
    monkeypatch.setenv("LIBRARIUM_CENSUS_CONCURRENCY", value)
    assert runpy.run_path(settings_module.__file__)["COVER_CENSUS_OBSERVATION_WORKERS"] == int(
        value
    )


@pytest.mark.parametrize("value", ["", "zero", "0", "-1", "9"])
def test_invalid_capacity_refuses_startup(monkeypatch, value):
    monkeypatch.setenv("LIBRARIUM_CENSUS_CONCURRENCY", value)
    with pytest.raises(ImproperlyConfigured, match="LIBRARIUM_CENSUS_CONCURRENCY"):
        runpy.run_path(settings_module.__file__)
