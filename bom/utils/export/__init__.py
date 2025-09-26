
from django.contrib.auth.models import AbstractUser


def is_superuser(user: AbstractUser):
    return user.is_superuser