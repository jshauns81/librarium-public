"""Exact scoped approval seals; transport possession alone grants no write permission."""

import hashlib
import hmac
from copy import deepcopy

from librarium.delivery_broker import canonical


class AuthorizationError(Exception):
    pass


def seal(payload, key):
    if type(key) is not bytes or len(key) < 32:
        raise AuthorizationError("signing_key_unavailable")
    payload = deepcopy(payload)
    return {
        "payload": payload,
        "signature": hmac.digest(key, canonical(payload), hashlib.sha256).hex(),
    }


def verify(grant, key):
    if type(grant) is not dict or set(grant) != {"payload", "signature"}:
        raise AuthorizationError("approval_invalid")
    expected = seal(grant["payload"], key)["signature"]
    if type(grant["signature"]) is not str or not hmac.compare_digest(expected, grant["signature"]):
        raise AuthorizationError("approval_invalid")
    return deepcopy(grant["payload"])
