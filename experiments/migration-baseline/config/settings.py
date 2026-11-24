"""Loopback-only settings for the experiment. These are not deployment settings."""

import os
from pathlib import Path

from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent
LAB_ROOT = BASE_DIR
SECRET_KEY = os.environ.get("LIBRARIUM_SECRET_KEY") or get_random_secret_key()
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
INSTALLED_APPS = ["librarium_lab"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "librarium_lab.views.SecurityHeaders",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates",
              "APP_DIRS": True, "OPTIONS": {"context_processors": []}}]
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
