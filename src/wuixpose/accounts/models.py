from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """A person who signs in to WUIXpose.

    Other tables point at this model's primary key, never at an email address or username, since
    both can change.
    """
