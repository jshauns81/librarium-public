"""A dispatcher credential must not manufacture reviewer approval."""

from copy import deepcopy

import pytest
from librarium.delivery_authorization import AuthorizationError, seal, verify

SECRET = b"synthetic-signing-key-" * 3


def test_grant_authenticates_exact_immutable_scope():
    intent = {
        "operation_id": "fixture",
        "output": {"sha256": "a" * 64},
        "reviewer": "opaque-principal",
    }
    signed = seal(intent, SECRET)
    assert verify(signed, SECRET) == intent
    intent["output"]["sha256"] = "b" * 64
    assert verify(signed, SECRET)["output"]["sha256"] == "a" * 64
    changed = deepcopy(signed)
    changed["payload"]["output"]["sha256"] = "c" * 64
    with pytest.raises(AuthorizationError):
        verify(changed, SECRET)


def test_transport_token_and_forged_boolean_do_not_grant_writer_permission():
    with pytest.raises(AuthorizationError):
        verify(seal({"approved": True}, b"different-transport-key" * 3), SECRET)
    with pytest.raises(AuthorizationError):
        verify({"approved": True}, SECRET)


@pytest.mark.parametrize("secret", [b"", b"short"])
def test_weak_signing_key_refuses(secret):
    with pytest.raises(AuthorizationError):
        seal({}, secret)
