from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """People who sign in. Its own app because Django requires AUTH_USER_MODEL to be created in its
    app's first migration, and core's was applied long before there was a user model."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "wuixpose.accounts"
