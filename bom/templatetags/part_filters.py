import datetime
from urllib.parse import urlparse

from django import template
from django.utils import timezone
from django.template.defaultfilters import stringfilter
from django.utils.dateparse import parse_date

register = template.Library()


@register.filter
@stringfilter
def get_domain(url):
    """ Get the domain name string from a URL. """
    return urlparse(url).netloc


@register.filter
def date_in_past(check_date):
    """Is a given date or datetime (or string) in the past (or today)? If None or invalid, returns False."""
    if not check_date:
        return False
    # If it's a datetime object
    if isinstance(check_date, datetime.datetime):
        return check_date.date() <= timezone.now().date()
    # If it's a string, try to parse as date (YYYY-MM-DD)
    # This happens when the form validation fails.
    if isinstance(check_date, str):
        dt = parse_date(check_date)
        if dt:
            return dt <= timezone.now().date()
        else:
            return False
    return False


@register.simple_tag
def find_assemblies_using_part(part):
    """
    Find a reference to all assemblies that currently use this part.

    Syntax::

        {% find_assemblies_using_part obj as "assemblies" %}
    """
    assys = [assy for assy in set(part.find_using_assemblies())]
    return assys


@register.filter
def get_item(dictionary, key):
    """ Look up an item from a dictionary.

    Syntax::

        {{ mydict|get_item:item.NAME }}
    """
    return dictionary.get(key)


@register.filter
def if_none(item, default):
    """ If an item is None, replace with a default.

    Syntax::
        {{ item|if_none:0 }}
    """
    return default if not item else item
