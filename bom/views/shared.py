""" Helpers every view area shares: reading the referer, bouncing back with a message. """
from urllib.parse import urlparse

from django.urls import Resolver404, reverse_lazy, resolve


def get_path_from_referer(referer):
    """Extract the path from a referer URL using urlparse."""
    if referer:
        parsed_url = urlparse(referer)
        return parsed_url.path
    return referer


def redirect_back_with_message(
    request, message, message_key="error_message", default_url=None, namespace_check="bom", allowed_views=None
):
    """
    Helper function to set an error message and redirect back to the referrer page.

    Args:
        request: The Django request object
        message: The message to store in the session
        message_key: The session key to store the message under (defaults to 'error_message')
        default_url: The URL to redirect to if the referrer can't be resolved (defaults to 'bom:start')
        namespace_check: The namespace to check against resolved URLs (defaults to 'bom')
        allowed_views: A dictionary mapping view names to tuples of (url_name, kwarg_key) for redirection
                    Example: {'part_editor_update': ('bom:part_editor_update', 'pk')}

    Returns:
        A URL to redirect to
    """
    # Store the message in the session
    request.session[message_key] = message

    # If no allowed views are specified, use a default set
    if allowed_views is None:
        allowed_views = {
            "part_editor_update": ("bom:part_editor_update", "pk"),
            "assembly_editor_update": ("bom:assembly_editor_update", "pk"),
            "start": ("bom:start", None),
            "dashboard": ("bom:start", None),
        }

    # Get the default URL if not provided
    if default_url is None:
        default_url = reverse_lazy("bom:start")

    # Try to get and parse the referrer
    referer = request.META.get("HTTP_REFERER")
    if referer:
        try:
            path = get_path_from_referer(referer)
            resolved = resolve(path)

            # Check if we're coming from an allowed view in the specified namespace
            if resolved.namespace == namespace_check and resolved.url_name in allowed_views:
                url_name, kwarg_key = allowed_views[resolved.url_name]

                # If the view needs a parameter (e.g., pk), get it from the resolved kwargs
                if kwarg_key and kwarg_key in resolved.kwargs:
                    return reverse_lazy(url_name, kwargs={kwarg_key: resolved.kwargs.get(kwarg_key)})
                else:
                    return reverse_lazy(url_name)
        except (ValueError, AttributeError, Resolver404):
            # A referer we cannot parse, or one that is not a page of ours.
            pass

    # Default fallback if the referrer couldn't be resolved or wasn't in allowed_views
    return default_url
