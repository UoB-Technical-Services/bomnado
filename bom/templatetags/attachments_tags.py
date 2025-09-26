from django import template
from bom.models import Attachment

register = template.Library()


@register.filter
def to_model_name(instance):
    """ Get the name of a given model instance's classname. E.g. `Part` """
    return instance.__class__.__name__


@register.simple_tag
def attachments_count(instance):
    """
    Counts attachments that are attached to a given object.

    Syntax::

        {% attachments_count obj %}
    """
    return Attachment.objects.attachments_for_object(instance).count()


@register.simple_tag
def get_attachments_for(instance, *args, **kwargs):
    """
    Resolves attachments that are attached to a given object. You can specify
    the variable name in the context the attachments are stored using the `as`
    argument.

    Syntax::

        {% get_attachments_for obj as "my_attachments" %}
    """
    return Attachment.objects.attachments_for_object(instance)
