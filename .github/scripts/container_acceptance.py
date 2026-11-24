"""Executed over stdin inside the built web container; no test packages required."""

import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

ORIGIN = "https://lib.example.org"
client = urllib.request.build_opener()


def request(path, body=None, csrf=None, key=None):
    headers = {"Host": "lib.example.org", "X-Forwarded-Proto": "https", "Origin": ORIGIN}
    if csrf:
        headers["X-CSRFToken"] = csrf
        headers["Cookie"] = f"librarium_csrftoken={csrf}"
    if key:
        headers["Idempotency-Key"] = key
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        "http://127.0.0.1:8123" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    with client.open(req, timeout=5) as response:
        return json.load(response), response


if len(sys.argv) > 1 and sys.argv[1] == "jobs":
    session, _ = request("/api/session")
    job, _ = request("/api/jobs", {"work_id": "demo-00001"}, session["csrf"], str(uuid.uuid4()))
    for _ in range(40):
        result, _ = request("/api/jobs/" + job["id"])
        listing, _ = request("/api/works")
        assert listing["total"] == 2
        if result["state"] == "succeeded":
            assert len(result["result"]["findings"]) >= 2
            print("PASS: CSRF intent, independent worker, responsive reads and durable findings")
            break
        time.sleep(0.5)
    else:
        raise AssertionError("Independent worker did not complete its inspection")
    raise SystemExit(0)

health, _ = request("/api/health")
assert health == {"status": "ready"}
listing, _ = request("/api/works")
assert listing["total"] == 0, "Deployment must not seed demo data automatically"
session, response = request("/api/session")
assert "Secure" in response.headers.get("Set-Cookie", "")
catalogue, _ = request("/api/catalogue")
assert catalogue == {"status": "not_configured"}

req = urllib.request.Request(
    "http://127.0.0.1:8123/", headers={"Host": "lib.example.org", "X-Forwarded-Proto": "https"}
)
with client.open(req, timeout=5) as response:
    html = response.read().decode()
    assert "Content-Security-Policy" in response.headers
    assert response.headers.get("Strict-Transport-Security") == "max-age=3600"
    assert "/assets/" in html
for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html):
    req = urllib.request.Request(
        "http://127.0.0.1:8123" + asset,
        headers={"Host": "lib.example.org", "X-Forwarded-Proto": "https"},
    )
    with client.open(req, timeout=5) as response:
        assert response.status == 200
print("PASS: empty installation, readiness, HTTPS cookie, built assets and security headers")
