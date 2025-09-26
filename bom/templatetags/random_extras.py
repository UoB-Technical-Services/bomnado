from django import template
import uuid

register = template.Library()

@register.simple_tag
def random_uuid():
    """
    Returns a random UUID string.
    Usage: {% random_uuid as random_id %}
    """
    return uuid.uuid4().hex
