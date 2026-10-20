import json
import os
import subprocess
import sys

LOAD_SETTINGS = "from django.conf import settings; print(settings.DEBUG, settings.ALLOWED_HOSTS)"


def load_settings(script: str = LOAD_SETTINGS, **env_overrides: str) -> subprocess.CompletedProcess:
    """Import settings in a fresh interpreter, since they're read once at startup."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "WUIXPOSE_"))}
    # Point away from any local .env so only the variables given here count.
    env |= {"DJANGO_SETTINGS_MODULE": "wuixpose.config.settings", "DJANGO_ENV_FILE": "/nonexistent"}
    env |= env_overrides
    return subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=False)


def test_production_mode_requires_a_secret_key():
    result = load_settings(DJANGO_DEBUG="false")

    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY" in result.stderr


def test_production_mode_with_secret_key_allows_no_hosts_by_default():
    result = load_settings(DJANGO_DEBUG="false", DJANGO_SECRET_KEY="x" * 50)

    assert result.stdout.strip() == "False []"


def test_debug_mode_runs_without_a_secret_key():
    result = load_settings(DJANGO_DEBUG="true")

    assert result.stdout.strip() == "True ['localhost', '127.0.0.1']"


def test_allowed_hosts_from_environment():
    result = load_settings(DJANGO_DEBUG="false", DJANGO_SECRET_KEY="x" * 50, DJANGO_ALLOWED_HOSTS="a.example,b.example")

    assert result.stdout.strip() == "False ['a.example', 'b.example']"


LOAD_OIDC = "from django.conf import settings; import json; print(json.dumps(settings.SOCIALACCOUNT_PROVIDERS))"


def test_no_oidc_provider_by_default():
    result = load_settings(LOAD_OIDC, DJANGO_DEBUG="true")

    assert json.loads(result.stdout) == {}


def test_oidc_provider_from_environment():
    result = load_settings(
        LOAD_OIDC,
        DJANGO_DEBUG="true",
        WUIXPOSE_OIDC_SERVER_URL="https://auth.example/realms/wuixpose",
        WUIXPOSE_OIDC_CLIENT_ID="wuixpose",
        WUIXPOSE_OIDC_CLIENT_SECRET="s3cret",
    )

    [app] = json.loads(result.stdout)["openid_connect"]["APPS"]
    assert (app["provider_id"], app["client_id"], app["secret"]) == ("keycloak", "wuixpose", "s3cret")
    # Our own provider is trusted to vouch for an email, so its first sign-in links the local account.
    assert app["settings"] == {"server_url": "https://auth.example/realms/wuixpose", "email_authentication": True}
