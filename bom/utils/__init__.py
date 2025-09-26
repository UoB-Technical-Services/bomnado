from functools import wraps
from bom.models import Team
from django.core.exceptions import PermissionDenied
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied


def team_owner_required(view_func):
    @wraps(view_func)
    def _wrapped_view(self, *args, **kwargs):
        request = self.request
        team_id = kwargs.get("pk")

        try:
            team = request.user.team_set.get(id=team_id)
        except Team.DoesNotExist:
            raise PermissionDenied("Team not found or access denied.")
        if not team.is_owner(request.user):
            raise PermissionDenied("Only the team owner can perform this action.")
        return view_func(self, *args, **kwargs)

    return _wrapped_view


def team_member_required(view_func):
    """Decorator that checks if a user is a member of the team associated with the object being accessed"""

    @wraps(view_func)
    def _wrapped_view(self, request, *args, **kwargs):

        # Get the object ID from kwargs
        pk = kwargs.get("pk")
        if not pk:
            return view_func(self, request, *args, **kwargs)

        # Get the object from the ViewSet's queryset
        queryset = self.get_queryset()
        try:
            obj = queryset.get(pk=pk)
        except Exception:
            raise DRFPermissionDenied("Resource not found or access denied.")

        # Check team membership
        if hasattr(obj, "team"):
            if not request.user.team_set.filter(id=obj.team.id).exists():
                raise PermissionDenied("You are not a member of this team.")
        elif hasattr(obj, "part") and hasattr(obj.part, "team"):
            if not request.user.team_set.filter(id=obj.part.team.id).exists():
                raise PermissionDenied("You are not a member of this team.")
        elif hasattr(obj, "subassembly") and hasattr(obj.subassembly, "team"):
            if not request.user.team_set.filter(id=obj.subassembly.team.id).exists():
                raise PermissionDenied("You are not a member of this team.")

        return view_func(self, request, *args, **kwargs)

    return _wrapped_view


_mono = 0


def monotonic_id():
    """
    This is used to generate a guaranteed monotonically increasing over the running lifetime of the application
    instance. This is used in generated the widgets in formsets that have to be initialised with an explicit id.
    e.g. the markdown editor. This as the formset widgets do not have a concept of the model instance at creation time.
    """
    global _mono
    _mono += 1
    return _mono
