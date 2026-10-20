from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """A person who signs in to WUIXpose.

    Other tables point at this model's primary key, never at an email address or username: both can
    change, and once an OIDC provider is connected a user's identity there is a separate allauth
    SocialAccount row (provider and subject) linked to this one, so connecting one adds rows rather
    than rewriting any.
    """
