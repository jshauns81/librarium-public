"""Opt-in identity handoff from an authenticated, IP-pinned ingress."""

import re
from ipaddress import ip_address

OPERATOR_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,255}")


class TrustedOperatorIdentity:
    def __init__(self, application, proxy_ips: str | None = ""):
        self.application = application
        proxy_ips = proxy_ips or ""
        try:
            if "%" in proxy_ips:
                raise ValueError
            self.proxy_ips = (
                frozenset(ip_address(value.strip()) for value in proxy_ips.split(","))
                if proxy_ips
                else frozenset()
            )
        except ValueError:
            raise ValueError(
                "LIBRARIUM_OPERATOR_PROXY_IPS must be empty or comma-separated literal IP addresses"
            ) from None

    def __call__(self, environ, start_response):
        # No ambient identity survives, including a server-promoted HTTP header.
        environ.pop("REMOTE_USER", None)
        environ.pop("HTTP_REMOTE_USER", None)
        value = environ.pop("HTTP_X_LIBRARIUM_OPERATOR", None)
        peer = environ.get("REMOTE_ADDR")
        if self.proxy_ips and isinstance(peer, str) and "%" not in peer:
            try:
                trusted = ip_address(peer) in self.proxy_ips
            except ValueError:
                trusted = False
            if trusted and isinstance(value, str) and OPERATOR_NAME.fullmatch(value):
                environ["REMOTE_USER"] = value
        return self.application(environ, start_response)


def principal(request):
    """The server-authenticated operator name, or None.

    WSGI REMOTE_USER is set only by the trusted ingress wrapper above. An HTTP
    Remote-User header is never accepted.
    """
    value = request.META.get("REMOTE_USER")
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None
