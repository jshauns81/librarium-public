"""Protected operator confirmation, bound to one book and one signed approval."""

import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

from librarium.delivery_writer import WriterError, read_secret


def validate_session(value, target):
    try:
        if (
            type(value) is not dict
            or set(value)
            != {
                "session_id",
                "target",
                "confirmed_by_sha256",
                "confirmed_at",
                "other_writers_stopped",
            }
            or str(uuid.UUID(value["session_id"])) != value["session_id"]
            or value["target"] != target
            or value["other_writers_stopped"] is not True
            or len(value["confirmed_by_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in value["confirmed_by_sha256"])
        ):
            raise ValueError
        confirmed = datetime.fromisoformat(value["confirmed_at"])
        if confirmed.tzinfo is None or not datetime.now(UTC) - timedelta(
            minutes=5
        ) <= confirmed <= datetime.now(UTC):
            raise ValueError
    except ValueError, TypeError, KeyError, AttributeError:
        raise WriterError("supervised_session_required") from None
    return value


def approval_session(path, target, principal, key):
    try:
        value = json.loads(read_secret(path))
        if (
            set(value)
            != {"session_id", "target", "confirmed_by", "confirmed_at", "other_writers_stopped"}
            or value.pop("confirmed_by") != principal
        ):
            raise ValueError
        value["confirmed_by_sha256"] = hmac.digest(
            key, b"librarium.principal.v1\0" + principal.encode(), "sha256"
        ).hex()
        return validate_session(value, target)
    except OSError, ValueError, TypeError, WriterError:
        raise WriterError("supervised_session_required") from None
