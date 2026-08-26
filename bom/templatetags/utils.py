from django import template

from bom import library
from bom.models import SubAssembly
from django.utils.html import escape
from django.contrib.auth.models import AbstractUser
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe
import bom.utils.export
from django.apps import apps

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def numeric_range(value):
    return range(value)


def _is_pcb(item, model_name, attr):
    """ Whether a part / assembly has the PCB multi-table child. """
    try:
        pcb_model = apps.get_model('bom', model_name)
        getattr(item, attr)
        return True
    except (pcb_model.DoesNotExist, AttributeError, LookupError):
        return False


def reference_html(item, kind=None, marks=True, href=None, extra_class=''):
    """ A part or assembly reference as it appears everywhere: an underline coloured by kind, the
    reference, then its marks - a red dot for open feedback, an amber dot for missing data, struck
    through when deprecated, a small tag for a sale code or a PCB. The same markup the library, the
    BOM table, the tree, markdown and the AI's answers use; `Bomnado.marks` builds it in the browser. """
    kind = kind or ('assembly' if isinstance(item, SubAssembly) else 'part')
    href = href or reverse_lazy('bom:part_editor_update' if kind == 'part' else 'bom:assembly_editor_update',
                                kwargs={'pk': item.id})
    classes = f'bn-ref is-{kind} bomlink {kind}'
    if extra_class:
        classes += ' ' + extra_class
    titles = [item.name] if getattr(item, 'name', '') else []
    bits = [f'<span class="reference">{escape(item.reference)}</span>']
    if marks:
        for mark, label in library.marks(item):
            if mark == 'deprecated':
                classes += ' is-deprecated'
                titles.append(label)
            elif mark == 'sale':
                bits.append(f'<span class="bn-tag" title="{escape(label)}">sale</span>')
            else:
                bits.append(f'<span class="bn-mark is-{mark}" title="{escape(label)}" aria-label="{escape(label)}"></span>')
    if _is_pcb(item, 'PCBPart' if kind == 'part' else 'PCBSubAssembly', 'pcbpart' if kind == 'part' else 'pcbsubassembly'):
        bits.append('<span class="bn-tag">PCB</span>')
    title = f' title="{escape("; ".join(titles))}"' if titles else ''
    return mark_safe(f'<a class="{classes}" href="{href}"{title}>{"".join(bits)}</a>')


@register.filter
def stylised_part(item):
    return reference_html(item, 'part')


@register.filter(is_safe=True)
def stylised_assembly(item):
    return reference_html(item, 'assembly')


@register.simple_tag
def filter_by_attr(items, attributes, expected_value, test='=='):
    """ Filters a sequence of objects by applying a test to the specified attribute of
    each object, and only selecting the objects with the test succeeding.

    If no test is specified, the attributes value will be evaluated as a boolean.

    Args:
        items (list): List of items to filter.
        attributes (str): List of attributes search for. `foo.bar` will check: `item.foo.bar`
        expected_value (any): Value to test is equal or not equal too.
        test (str): Operator string, either 'bool', '==' or '!=' to test coercion, equality or
            inequality respectively.

    Returns:
        list: Filtered list of items with a matching property that passes the selected test.

    Usage:
        {% filter_by_attr my_list 'foo.bar' True 'bool' as my_list_filtered %}
        {% if my_list_filtered %}
            <h1>Heading</h1>
            {% for item in my_list_filtered %}
                {{ item.foo.bar }}
            {% endfor %}
        {% endif %}
    """
    output = []
    attributes = attributes.split('.')
    for item in items:

        # Find the attribute to test - skip if not there.
        node = item
        try:
            for attr in attributes:
                node = getattr(node, attr)
        except AttributeError:
            continue

        # Test the attribute.
        if test == '==':
            if node == expected_value:
                output.append(item)
        elif test == '!=':
            if node != expected_value:
                output.append(item)
        elif test == 'bool':
            if bool(node) == expected_value:
                output.append(item)
        else:
            raise ValueError('test parameter must be == or !=')

    return output

@register.simple_tag
def is_superuser(user: AbstractUser):
    return bom.utils.export.is_superuser(user)


@register.filter
def is_pcb_part_missing_lcsc(item):
    """Return True when item is a PCBPart and has no LCSC part number."""
    try:
        pcb = item.pcbpart
    except Exception:
        return False
    return not bool((pcb.LCSCPartNo or '').strip())


@register.filter
def initials(user):
    """ "HE" for Hugh Evans, "J" for john, "?" for nobody: the avatar in the top bar. """
    if user is None or not getattr(user, 'is_authenticated', False):
        return '?'
    names = [n for n in (user.first_name, user.last_name) if n]
    if names:
        return ''.join(n[0] for n in names)[:2].upper()
    return (user.email or user.username or '?')[:1].upper()
