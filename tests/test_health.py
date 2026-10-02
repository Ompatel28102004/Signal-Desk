from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_reports_application_configuration() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["application"]["status"] == "running"
    assert payload["database"]["status"] in {"configured", "not_configured"}
    assert payload["environment"]["name"]
    assert payload["environment"]["status"] == "active"