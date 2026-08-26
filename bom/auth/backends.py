from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """ Authenticate with an email address (case-insensitive) and password.

    Older databases may hold more than one account with the same address, so
    this never assumes the lookup is unique: each candidate is checked against
    the password and the first that matches (and is active) is returned.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        user_model = get_user_model()
        candidates = user_model.objects.filter(email__iexact=username).order_by('pk')

        matched = None
        for user in candidates:
            if user.check_password(password) and self.user_can_authenticate(user):
                matched = user
                break

        if matched is None and not candidates.exists():
            # Run the password hasher once anyway, so an unknown address takes as
            # long to reject as a wrong password does (mirrors ModelBackend).
            user_model().set_password(password)

        return matched
