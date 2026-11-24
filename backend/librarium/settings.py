import getpass
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.environ.get("LIBRARIUM_SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "Set LIBRARIUM_SECRET_KEY to an explicit random value of at least 50 characters"
    )
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
ROOT_URLCONF = "librarium.urls"
LIBRARIUM_OPERATOR_PROXY_IPS = os.environ.get("LIBRARIUM_OPERATOR_PROXY_IPS", "")
INSTALLED_APPS = ["django.contrib.contenttypes", "librarium"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
DATABASES: dict[str, dict[str, Any]] = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PGDATABASE", "librarium"),
        "USER": os.environ.get("LIBRARIUM_RUNTIME_DB_USER")
        or os.environ.get("PGUSER")
        or getpass.getuser(),
        "HOST": os.environ.get("PGHOST", str(BASE_DIR / ".local/postgres-socket")),
        "PORT": os.environ.get("PGPORT", "55432"),
        "PASSWORD": os.environ.get(
            "LIBRARIUM_RUNTIME_DB_PASSWORD", os.environ.get("PGPASSWORD", "")
        ),
        # Listings served from Postgres would otherwise spend most of their time connecting.
        "CONN_MAX_AGE": int(os.environ.get("LIBRARIUM_DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 4096
LIBRARIUM_LIBRARY_URL = os.environ.get("LIBRARIUM_LIBRARY_URL", "")
DIRECT_LIBRARY_ROOT = os.environ.get("LIBRARIUM_DIRECT_LIBRARY_ROOT", "")
if DIRECT_LIBRARY_ROOT and (
    not Path(DIRECT_LIBRARY_ROOT).is_absolute()
    or "\x00" in DIRECT_LIBRARY_ROOT
    or any(part in {"", ".", ".."} for part in DIRECT_LIBRARY_ROOT.split("/")[1:])
):
    raise ImproperlyConfigured(
        "LIBRARIUM_DIRECT_LIBRARY_ROOT must be an absolute library directory"
    )
# off: the direct reader serves listings and nothing is imported. refresh: the worker keeps
# the Postgres read model current for parity checks. serve: listings come from it.
LIBRARY_READ_MODEL = os.environ.get("LIBRARIUM_LIBRARY_READ_MODEL", "off")
if LIBRARY_READ_MODEL not in {"off", "refresh", "serve"}:
    raise ImproperlyConfigured("LIBRARIUM_LIBRARY_READ_MODEL must be off, refresh or serve")
LIBRARY_READ_MODEL_SECONDS = float(os.environ.get("LIBRARIUM_LIBRARY_READ_MODEL_SECONDS", "15"))
if not 1 <= LIBRARY_READ_MODEL_SECONDS <= 3600:
    raise ImproperlyConfigured("LIBRARIUM_LIBRARY_READ_MODEL_SECONDS must be 1 to 3600")
try:
    COVER_CENSUS_OBSERVATION_WORKERS = int(
        os.environ.get(
            "LIBRARIUM_CENSUS_CONCURRENCY", str(max(1, min(4, (os.cpu_count() or 1) // 2)))
        )
    )
except ValueError:
    raise ImproperlyConfigured("LIBRARIUM_CENSUS_CONCURRENCY must be 1 to 8") from None
if not 1 <= COVER_CENSUS_OBSERVATION_WORKERS <= 8:
    raise ImproperlyConfigured("LIBRARIUM_CENSUS_CONCURRENCY must be 1 to 8")
LIBRARIUM_ARTIFACT_DIR = os.environ.get("LIBRARIUM_ARTIFACT_DIR", "")
LIBRARIUM_REFERENCE_STATE_DIR = os.environ.get("LIBRARIUM_REFERENCE_STATE_DIR", "")
if LIBRARIUM_REFERENCE_STATE_DIR and (
    not Path(LIBRARIUM_REFERENCE_STATE_DIR).is_absolute()
    or "\x00" in LIBRARIUM_REFERENCE_STATE_DIR
    or any(part in {"", ".", ".."} for part in LIBRARIUM_REFERENCE_STATE_DIR.split("/")[1:])
):
    raise ImproperlyConfigured(
        "LIBRARIUM_REFERENCE_STATE_DIR must be an absolute private directory"
    )
# Curated content references: one exact operator-selected registry file and its digest.
LIBRARIUM_CONTENT_TRUST_REGISTRY = os.environ.get("LIBRARIUM_CONTENT_TRUST_REGISTRY", "")
LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256 = os.environ.get(
    "LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256", ""
)
if bool(LIBRARIUM_CONTENT_TRUST_REGISTRY) != bool(LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256) or (
    LIBRARIUM_CONTENT_TRUST_REGISTRY
    and (
        not Path(LIBRARIUM_CONTENT_TRUST_REGISTRY).is_absolute()
        or "\x00" in LIBRARIUM_CONTENT_TRUST_REGISTRY
        or any(part in {"", ".", ".."} for part in LIBRARIUM_CONTENT_TRUST_REGISTRY.split("/")[1:])
        or len(LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256) != 64
        or any(char not in "0123456789abcdef" for char in LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256)
    )
):
    raise ImproperlyConfigured(
        "Set LIBRARIUM_CONTENT_TRUST_REGISTRY to an absolute registry file together with its "
        "lowercase LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256"
    )
LIBRARIUM_EPUBCHECK_DIR = os.environ.get("LIBRARIUM_EPUBCHECK_DIR", "")
LIBRARIUM_JAVA = os.environ.get("LIBRARIUM_JAVA", "")
for option in ("LIBRARIUM_EPUBCHECK_DIR", "LIBRARIUM_JAVA"):
    value = globals()[option]
    if value and (
        not Path(value).is_absolute()
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in value.split("/")[1:])
    ):
        raise ImproperlyConfigured(f"{option} must be an absolute configured path")
if LIBRARIUM_ARTIFACT_DIR and (
    not Path(LIBRARIUM_ARTIFACT_DIR).is_absolute()
    or "\x00" in LIBRARIUM_ARTIFACT_DIR
    or any(part in {"", ".", ".."} for part in LIBRARIUM_ARTIFACT_DIR.split("/")[1:])
):
    raise ImproperlyConfigured("LIBRARIUM_ARTIFACT_DIR must be an absolute persistent directory")
if LIBRARIUM_LIBRARY_URL:
    from librarium.library import origin as library_origin

    library_origin(LIBRARIUM_LIBRARY_URL)

LIBRARIUM_CATALOGUE_STATUS_URL = os.environ.get("LIBRARIUM_CATALOGUE_STATUS_URL", "")
LIBRARIUM_CATALOGUE_STATUS_PAGE_URL = os.environ.get("LIBRARIUM_CATALOGUE_STATUS_PAGE_URL", "")
LIBRARIUM_CATALOGUE_DIR = os.environ.get("LIBRARIUM_CATALOGUE_DIR", "")
LIBRARIUM_CATALOGUE_SYNC_ENABLED = os.environ.get(
    "LIBRARIUM_CATALOGUE_SYNC_ENABLED", ""
).lower() in {"1", "true"}
LIBRARIUM_CATALOGUE_FIXTURE = os.environ.get("LIBRARIUM_CATALOGUE_FIXTURE") == "1"
LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR = os.environ.get(
    "LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR"
) or (str(Path(LIBRARIUM_CATALOGUE_DIR) / "upscaled") if LIBRARIUM_CATALOGUE_DIR else "")
if LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR and (
    not Path(LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR).is_absolute()
    or "\x00" in LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR
):
    raise ImproperlyConfigured(
        "LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR must be an absolute local directory"
    )
LIBRARIUM_CATALOGUE_COVER_DIR = os.environ.get("LIBRARIUM_CATALOGUE_COVER_DIR") or (
    str(Path(LIBRARIUM_CATALOGUE_DIR) / "covers") if LIBRARIUM_CATALOGUE_DIR else ""
)
if LIBRARIUM_CATALOGUE_COVER_DIR and (
    not Path(LIBRARIUM_CATALOGUE_COVER_DIR).is_absolute() or "\x00" in LIBRARIUM_CATALOGUE_COVER_DIR
):
    raise ImproperlyConfigured("LIBRARIUM_CATALOGUE_COVER_DIR must be an absolute local directory")
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_NAME = "librarium_csrftoken"
X_FRAME_OPTIONS = "DENY"
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

PUBLIC_ORIGIN = os.environ.get("LIBRARIUM_PUBLIC_ORIGIN", "").rstrip("/")
if PUBLIC_ORIGIN:
    origin = urlsplit(PUBLIC_ORIGIN)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
        or os.environ.get("LIBRARIUM_TRUST_PROXY") != "1"
    ):
        raise ImproperlyConfigured(
            "Public deployment requires an HTTPS origin without paths and LIBRARIUM_TRUST_PROXY=1"
        )
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", origin.hostname]
    CSRF_TRUSTED_ORIGINS = [PUBLIC_ORIGIN]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^api/health$"]
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600


# The isolated library-write path is a separate opt-in role; web and worker never run it.
LIBRARIUM_WRITER_TOKEN_FILE = os.environ.get("LIBRARIUM_WRITER_TOKEN_FILE", "")
MIDDLEWARE.insert(0, "librarium.views.NoStoreMiddleware")
CSRF_FAILURE_VIEW = "librarium.views.csrf_failure"

# Opt-in network role; neither web nor worker receives an external route.
LIBRARIUM_COVER_SOURCES_ENABLED = (
    os.environ.get("LIBRARIUM_COVER_SOURCES_ENABLED", "false") == "true"
)

LIBRARIUM_COVER_SOURCES_SECRET = os.environ.get("LIBRARIUM_COVER_SOURCES_SECRET", "")

LIBRARIUM_SOURCE_BROWSER_ENABLED = (
    os.environ.get("LIBRARIUM_SOURCE_BROWSER_ENABLED", "false") == "true"
)
LIBRARIUM_SOURCE_BROWSER_SECRET = os.environ.get("LIBRARIUM_SOURCE_BROWSER_SECRET", "")
