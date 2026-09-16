import pytest


@pytest.mark.django_db
def test_liveness_without_business_data(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
