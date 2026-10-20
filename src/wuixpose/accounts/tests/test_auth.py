import re

import pytest
from allauth.account.models import EmailAddress
from django.core import mail

from wuixpose.accounts.models import User

API = "/api/auth/browser/v1"
EMAIL = "pat@example.com"
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def isolated_cache(settings):
    """Rate limit counts live in the cache; keep them out of the shared Redis and between tests."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


def verified_user(email: str = EMAIL, password: str = PASSWORD) -> User:
    user = User.objects.create_user(username=email, email=email, password=password)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def emailed_code() -> str:
    """The verification code in the last email sent."""
    match = re.search(r"^\s*([A-Z0-9]{4}-[A-Z0-9]{4})\s*$", mail.outbox[-1].body, re.MULTILINE)
    assert match, mail.outbox[-1].body
    return match[1]


@pytest.mark.django_db
def test_passwords_are_hashed_with_argon2():
    assert verified_user().password.startswith("argon2$argon2id$")


@pytest.mark.django_db
def test_signup_rejects_a_password_shorter_than_15_characters(client):
    response = client.post(
        f"{API}/auth/signup", {"email": EMAIL, "password": "fourteen chars"}, content_type="application/json"
    )

    assert response.status_code == 400
    assert not User.objects.exists()


@pytest.mark.django_db
def test_signup_signs_in_once_the_emailed_code_is_entered(client):
    response = client.post(
        f"{API}/auth/signup", {"email": EMAIL, "password": PASSWORD}, content_type="application/json"
    )

    assert response.status_code == 401
    assert [f["id"] for f in response.json()["data"]["flows"] if f.get("is_pending")] == ["verify_email"]
    assert client.get(f"{API}/auth/session").status_code == 401

    response = client.post(f"{API}/auth/email/verify", {"key": emailed_code()}, content_type="application/json")

    assert response.status_code == 200
    assert client.get(f"{API}/auth/session").json()["data"]["user"]["email"] == EMAIL


@pytest.mark.django_db
def test_login_and_logout(client):
    verified_user()

    response = client.post(f"{API}/auth/login", {"email": EMAIL, "password": PASSWORD}, content_type="application/json")
    assert response.status_code == 200
    assert client.get(f"{API}/auth/session").status_code == 200

    client.delete(f"{API}/auth/session")
    assert client.get(f"{API}/auth/session").status_code == 401


@pytest.mark.django_db
def test_repeated_wrong_passwords_are_rate_limited(client):
    verified_user()
    wrong = {"email": EMAIL, "password": "not the password at all"}

    for _ in range(5):
        client.post(f"{API}/auth/login", wrong, content_type="application/json")
    right = {"email": EMAIL, "password": PASSWORD}
    response = client.post(f"{API}/auth/login", right, content_type="application/json")

    assert response.status_code == 400
    assert [e["code"] for e in response.json()["errors"]] == ["too_many_login_attempts"]


@pytest.mark.django_db
def test_no_sign_in_providers_unless_one_is_configured(client):
    assert client.get(f"{API}/config").json()["data"]["socialaccount"]["providers"] == []


@pytest.mark.django_db
def test_a_configured_oidc_provider_is_offered(client, settings):
    settings.SOCIALACCOUNT_PROVIDERS = {
        "openid_connect": {
            "APPS": [
                {
                    "provider_id": "keycloak",
                    "name": "Keycloak",
                    "client_id": "wuixpose",
                    "secret": "secret",
                    "settings": {"server_url": "https://auth.example/realms/wuixpose", "email_authentication": True},
                }
            ]
        }
    }

    providers = client.get(f"{API}/config").json()["data"]["socialaccount"]["providers"]

    assert [(p["id"], p["name"]) for p in providers] == [("keycloak", "Keycloak")]


@pytest.mark.django_db
def test_a_superuser_signs_in_to_admin_by_email(client):
    # As createsuperuser makes one: no allauth EmailAddress row.
    User.objects.create_superuser(username="admin", email="admin@example.com", password=PASSWORD)

    response = client.post("/admin/login/", {"username": "admin@example.com", "password": PASSWORD})

    assert response.status_code == 302
    assert client.get("/admin/").status_code == 200
