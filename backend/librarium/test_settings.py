import os

os.environ.setdefault("LIBRARIUM_SECRET_KEY", "test-only-" + "x" * 60)

from librarium.settings import *

DATABASES["default"]["ENGINE"] = "librarium.testing.postgresql"
DATABASES["default"]["TEST"] = {"NAME": "test_" + DATABASES["default"]["NAME"]}
# Tests open connections from short-lived threads; persistent ones would outlive the test database.
DATABASES["default"]["CONN_MAX_AGE"] = 0
