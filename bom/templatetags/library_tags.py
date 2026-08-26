from django import template

from bom import library

register = template.Library()


@register.inclusion_tag('partial/library.html', takes_context=True)
def library_panel(context, selected=None, tab='parts'):
    """ The left-hand library: tabs, the new-record form, and the first page of the list.

    Syntax::

        {% library_panel part %}            - parts tab, this part selected
        {% library_panel assembly 'assemblies' %}
    """
    request = context['request']
    user = request.user
    selected_key = f'{"assembly" if tab == "assemblies" else "part"}:{selected.pk}' if selected is not None else ''
    context = {'request': request, 'user': user, 'tab': tab, 'selected': selected, 'selected_key': selected_key,
               'page': library.parts(user) if tab == 'parts' else library.assemblies(user),
               'query': '', 'which': 'all', 'view': 'list', 'teams': user.team_set.all()}
    if tab == 'assemblies':
        # The editor opens on the tree, with the assembly's branch unfolded.
        context['view'] = 'tree'
        context['tree'], context['orphans'] = library.assembly_tree(user, selected.pk if selected is not None else None)
    return context


@register.filter
def part_status(part):
    return library.part_status(part)


@register.filter
def assembly_status(assembly):
    return library.assembly_status(assembly)
