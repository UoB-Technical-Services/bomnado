""" The library region: the searchable part and assembly lists and the search overlay. """

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from bom.models import Part, SubAssembly
from bom import library


def _library_selected(request):
    """ The record the editor is showing, so the list can mark it: `?selected=part:12`. """
    text = request.GET.get('selected', '')
    kind, _, pk = text.partition(':')
    model = {'part': Part, 'assembly': SubAssembly}.get(kind)
    return model.objects.filter(pk=pk).first() if model and pk.isdigit() else None


@login_required(login_url='/accounts/login/')
def library_parts(request):
    """ The library's parts list, swapped by htmx on search, filter and page. """
    query = (request.GET.get('q') or '').strip()[:100]
    which = request.GET.get('which') or 'all'
    page = library.parts(request.user, query, which, request.GET.get('page') or 1)
    return render(request, 'partial/library_parts.html',
                  {'page': page, 'query': query, 'which': which if which in library.FILTERS else 'all',
                   'selected': _library_selected(request), 'selected_key': request.GET.get('selected', '')})


@login_required(login_url='/accounts/login/')
def library_assemblies(request):
    query = (request.GET.get('q') or '').strip()[:100]
    selected = _library_selected(request)
    view = 'tree' if request.GET.get('view') == 'tree' else 'list'
    context = {'query': query, 'selected': selected, 'selected_key': request.GET.get('selected', ''), 'view': view,
               'page': library.assemblies(request.user, query, request.GET.get('page') or 1)}
    if view == 'tree':
        context['tree'], context['orphans'] = library.assembly_tree(
            request.user, selected.pk if isinstance(selected, SubAssembly) else None, query)
    return render(request, 'partial/library_assemblies.html', context)


@login_required(login_url='/accounts/login/')
def library_search(request):
    """ The search overlay's results: the best parts and assemblies for the words typed. """
    query = (request.GET.get('q') or '').strip()[:100]
    parts = list(library.parts(request.user, query))[:8] if query else []
    assemblies = list(library.assemblies(request.user, query))[:6] if query else []
    return render(request, 'partial/search_results.html', {'query': query, 'parts': parts, 'assemblies': assemblies})
