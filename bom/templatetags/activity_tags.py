from django import template
from django.utils import timezone
from django.utils.html import escape, format_html
from django.utils.timesince import timesince

from bom.utils.activity import activity_context

register = template.Library()


@register.filter
def person(user):
    """ How the strip names someone: first name (and last, if set), else their email,
    as a mailto link. `Someone` when nothing was recorded. """
    if user is None:
        return 'Someone'
    name = ' '.join(part for part in (user.first_name, user.last_name) if part).strip() or user.email or user.username
    if user.email:
        return format_html('<a class="bomnado-person" href="mailto:{}" title="{}">{}</a>', user.email, user.email, name)
    return escape(name)


@register.filter
def ago(when):
    """ `just now`, else Django's `timesince` with "ago". """
    if when is None:
        return ''
    if (timezone.now() - when).total_seconds() < 60:
        return 'just now'
    return f'{timesince(when)} ago'


@register.inclusion_tag('partial/activity.html', takes_context=True)
def activity_strip(context, obj):
    """ The comments-and-activity strip for a part or assembly.

    Syntax::

        {% activity_strip part %}
    """
    return {**activity_context(obj), 'csrf_token': context.get('csrf_token'), 'request': context.get('request')}
