import re

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import HttpRequest

STRICT_POLICY = "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
# The reader page shows each book document in a blob: frame, which inherits
# this policy. Books carry their own style blocks and attributes, and the
# engine adds its own, so styles may be inline or blob:. Scripts never relax.
READER_POLICY = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' blob:; font-src 'self' data: blob:; img-src 'self' data: blob:; frame-src blob:; connect-src 'self'; media-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
READER_PATH = re.compile(r"/read/[^/]+/?")

HEADERS = {
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
REPLACED = {name.lower() for name in HEADERS} | {"content-security-policy"}


def policy_for(path: str) -> str:
    return READER_POLICY if READER_PATH.fullmatch(path) else STRICT_POLICY


class SecurityHeaders:
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        def secured(status, headers, exc_info=None):
            values = [(key, value) for key, value in headers if key.lower() not in REPLACED]
            if settings.SECURE_HSTS_SECONDS and request.is_secure():
                values = [
                    (key, value)
                    for key, value in values
                    if key.lower() != "strict-transport-security"
                ]
                values.append(
                    ("Strict-Transport-Security", f"max-age={settings.SECURE_HSTS_SECONDS}")
                )
            policy = ("Content-Security-Policy", policy_for(request.path_info))
            return start_response(status, [*values, *HEADERS.items(), policy], exc_info)

        request = HttpRequest()
        request.META = environ
        request.path_info = environ.get("PATH_INFO", "/")
        request.path = environ.get("SCRIPT_NAME", "") + request.path_info
        try:
            request.get_host()
        except DisallowedHost:
            secured("400 Bad Request", [("Content-Type", "text/plain")])
            return [b"Invalid host"]
        if (
            settings.SECURE_SSL_REDIRECT
            and not request.is_secure()
            and request.path != "/api/health"
        ):
            secured(
                "301 Moved Permanently",
                [
                    ("Location", f"https://{request.get_host()}{request.get_full_path()}"),
                    ("Content-Length", "0"),
                ],
            )
            return [b""]
        return self.application(environ, secured)
