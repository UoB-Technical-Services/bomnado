from django import template
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


@register.filter
def stylised_part(item):
    deprecated = ''
    if item.deprecated:
        deprecated_date = item.deprecated.strftime('%b %Y')
        deprecated = f'<span class="icon" title="Deprecated in {deprecated_date}.">⚠️</span> '

    reference = f'<span class="reference" title="{item.name}">{item.reference}</span>'
    url = reverse_lazy('bom:part_editor_update', kwargs={'pk': item.id})
    review = '<span title="Open feedback">👀 </span>' if item.has_open_feedback else ''

    sale_code = ''
    if item.sale_code:
        sale_code = f' <span class="icon" title="Sales Code = {item.sale_code}"> 📑</span>'

    kbd = f'<kbd>{review}{deprecated}{reference}{sale_code}'
    # Detect whether this part has a PCBPart multi-table child
    is_pcb_part = False
    try:
        pcb_model = apps.get_model('bom', 'PCBPart')
        try:
            _ = item.pcbpart
            is_pcb_part = True
        except pcb_model.DoesNotExist:
            is_pcb_part = False
    except Exception:
        is_pcb_part = False

    badge = ' <span class="badge bom-badge">PCB</span>' if is_pcb_part else ''
    # put the badge inside the kbd so it stays inline with the reference
    kbd = f'{kbd}{badge}</kbd>'
    link = f'<a class="bomlink part" href="{url}">{kbd}</a>'
    return mark_safe(link)


@register.filter(is_safe=True)
def stylised_assembly(item):
    deprecated = ''
    if item.deprecated:
        deprecated_date = item.deprecated.strftime('%b %Y')
        deprecated = f'<span class="icon" title="Deprecated in {deprecated_date}.">⚠️</span> '

    reference = f'<span class="reference" title="{item.name}">{item.reference}</span>'
    url = reverse_lazy('bom:assembly_editor_update', kwargs={'pk': item.id})
    review = '<span title="Open feedback">👀 </span>' if item.has_open_feedback else ''

    sale_code = ''
    if item.sale_code:
        sale_code = f' <span class="icon" title="Sales Code = {item.sale_code}"> 📑</span>'

    kbd = f'<kbd>{review}{deprecated}{reference}{sale_code}'
    # Detect whether this assembly has a PCBSubAssembly child (multi-table inheritance)
    is_pcb = False
    try:
        pcb_model = apps.get_model('bom', 'PCBSubAssembly')
        try:
            # Accessing the related object will raise pcb_model.DoesNotExist if not present
            _ = item.pcbsubassembly
            is_pcb = True
        except pcb_model.DoesNotExist:
            is_pcb = False
    except Exception:
        is_pcb = False

    badge = ' <span class="badge bom-badge">PCB</span>' if is_pcb else ''
    # put the badge inside the kbd so it stays inline with the reference
    kbd = f'{kbd}{badge}</kbd>'
    link = f'<a class="bomlink assembly" href="{url}">{kbd}</a>'
    return mark_safe(link)


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
