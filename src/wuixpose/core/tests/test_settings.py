import os
import subprocess
import sys

LOAD_SETTINGS = "from django.conf import settings; print(settings.DEBUG, settings.ALLOWED_HOSTS)"


def load_settings(**env_overrides: str) -> subprocess.CompletedProcess:
    """Import settings in a fresh interpreter, since they're read once at startup."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "WUIXPOSE_"))}
    # Point away from any local .env so only the variables given here count.
    env |= {"DJANGO_SETTINGS_MODULE": "wuixpose.config.settings", "DJANGO_ENV_FILE": "/nonexistent"}
    env |= env_overrides
    return subprocess.run(
        [sys.executable, "-c", LOAD_SETTINGS], env=env, capture_output=True, text=True, check=False
    )


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
