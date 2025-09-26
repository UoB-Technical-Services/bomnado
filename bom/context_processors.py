from django.conf import settings

def security_settings(request):
    """
    Adds security-related settings to the template context
    """
    # Only show warning to superusers
    show_warning = False
    if hasattr(settings, 'SHOW_KEY_WARNING') and settings.SHOW_KEY_WARNING:
        if request.user.is_authenticated and request.user.is_superuser:
            show_warning = True

    return {
        'SHOW_KEY_WARNING': show_warning,
    }