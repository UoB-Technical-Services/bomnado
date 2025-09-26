from rest_framework import permissions


class IsTeamMember(permissions.BasePermission):
    """
    Custom permission to only allow members of the same team to access objects.
    """

    def has_object_permission(self, request, view, obj):
        # Check if user is in the same team as the object
        if hasattr(obj, "team"):
            return request.user.team_set.filter(id=obj.team.id).exists()
        elif hasattr(obj, "part") and hasattr(obj.part, "team"):
            return request.user.team_set.filter(id=obj.part.team.id).exists()
        elif hasattr(obj, "subassembly") and hasattr(obj.subassembly, "team"):
            return request.user.team_set.filter(id=obj.subassembly.team.id).exists()
        elif hasattr(obj, "project") and hasattr(obj.project, "team"):
            return request.user.team_set.filter(id=obj.project.team.id).exists()
        return False
