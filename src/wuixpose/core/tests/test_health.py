from django.urls import reverse


def test_health_returns_ok(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_rejects_non_get(client):
    response = client.post(reverse("health"))

    assert response.status_code == 405
