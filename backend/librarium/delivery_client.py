"""Dispatcher-only RPC to the fixed local synthetic writer; no redirects or proxies."""

import http.client
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

from django.conf import settings

from librarium.delivery_writer import WriterError, parse, read_secret

_DEADLINE: ContextVar[float | None] = ContextVar("delivery_rpc_deadline", default=None)


@contextmanager
def rpc_deadline(seconds):
    token = _DEADLINE.set(monotonic() + seconds)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def rpc(path, value=None):
    deadline = _DEADLINE.get()
    remaining = 60 if deadline is None else min(60, deadline - monotonic())
    if remaining <= 0:
        raise WriterError("timeout")
    token = read_secret(settings.LIBRARIUM_WRITER_TOKEN_FILE)
    connection = http.client.HTTPConnection(
        "127.0.0.1", int(os.environ.get("LIBRARIUM_WRITER_PORT", "8133")), timeout=remaining
    )
    try:
        body = None if value is None else json.dumps(value, allow_nan=False).encode()
        connection.request(
            "GET" if value is None else "POST",
            path,
            body=body,
            headers={"Authorization": "Bearer " + token.hex(), "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise WriterError("writer_response_invalid")
        result = parse(data)
        if response.status != 200:
            raise WriterError(result.get("error", "writer_unavailable"))
        return result
    except OSError, http.client.HTTPException:
        raise WriterError("writer_unavailable") from None
    finally:
        connection.close()
