import pytest


def test_series_evidence_route_exposes_unconfigured_state(client, settings):
    settings.LIBRARIUM_LIBRARY_URL = ""
    result = client.get(
        "/api/library/series", {"series": "7", "version": "2026.10.24.2", "sha256": "a" * 64}
    )
    assert result.status_code == 200
    assert result.json() == {"status": "not_configured"}
    assert result.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("method", ["post", "put", "delete"])
@pytest.mark.parametrize("url", ["/api/library/series", "/api/library/works/w_fixture"])
def test_library_evidence_has_no_http_writer(client, method, url):
    assert getattr(client, method)(url).status_code == 405


def test_work_evidence_route_validates_its_exact_pin_contract(client, settings):
    settings.LIBRARIUM_LIBRARY_URL = ""
    assert client.get("/api/library/works/w_fixture").status_code == 400
    response = client.get(
        "/api/library/works/w_fixture", {"version": "2026.10.24.2", "sha256": "a" * 64}
    )
    assert response.json() == {"status": "not_configured"}
