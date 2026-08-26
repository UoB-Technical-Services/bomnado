""" The library: the searchable, filterable lists of parts and assemblies in the left-hand region,
and the status each row shows.

A status is computed from the record, never stored: "Needs review" when there is open
feedback, "Missing <what>" when a field a buyer needs is empty, "Deprecated", else "Complete" - which the
pages never show: complete is silent, broken is noisy (`Status.quiet`).
The filter pills ("Needs review", "Missing data") are the same rules, so what the row
says and what the filter finds never disagree.
"""
from dataclasses import dataclass

from django.core.paginator import Paginator
from django.db.models import Q

from bom.models import Part, SubAssembly

PAGE_SIZE = 12
FILTERS = ('all', 'attention', 'missing')

""" The marks a reference carries inline - coloured dots and small tags - defined once. Templates and
scripts build the same markup from `marks()` / `MARKS` (`Bomnado.marks` in the browser). """
MARKS = {'bad': 'Needs review', 'warn': 'Missing data', 'deprecated': 'Deprecated', 'sale': 'Sale code'}


@dataclass
class Status:
    label: str
    tone: str            # ok | warn | bad | muted (theme.css .bn-status.is-*)
    missing: list        # what a part lacks, in the order a buyer cares: weight, dimensions, colour, price, picture

    @property
    def needs_attention(self):
        return self.tone == 'bad'

    @property
    def quiet(self):
        """ True when there is nothing to say: the pages show no pill for a complete record. """
        return self.tone == 'ok'

    @property
    def is_missing(self):
        return bool(self.missing)


def part_status(part):
    """ What the library and the editor header say about a part. Every part needs a price and a
    picture. A part with a sale code is sold on its own, so a buyer also needs its weight,
    dimensions and colour; without a sale code those are optional. """
    missing = []
    if part.sale_code:
        if not part.kgs:
            missing.append('weight')
        if not part.dimensions:
            missing.append('dimensions')
        if not part.colour:
            missing.append('colour')
    if not any(source.rrp for source in part.sources.all()):
        missing.append('price')
    if not part.picture:
        missing.append('picture')
    if part.deprecated:
        return Status('Deprecated', 'muted', missing)
    if part.has_open_feedback:
        return Status('Needs review', 'bad', missing)
    if missing:
        return Status(f'Missing {missing[0]}', 'warn', missing)
    return Status('Complete', 'ok', missing)


def marks(record):
    """ `[(kind, label)]` for a part or assembly, in the order they are shown: bad (open feedback), warn
    (missing data - parts only), deprecated, sale. The same rules as the statuses, so a dot beside a
    reference and a pill in a list never disagree. """
    out = []
    if record.has_open_feedback:
        out.append(('bad', MARKS['bad']))
    if isinstance(record, Part):
        missing = part_status(record).missing
        if missing:
            out.append(('warn', 'Missing ' + ', '.join(missing)))
    if record.deprecated:
        out.append(('deprecated', 'Deprecated ' + record.deprecated.strftime('%b %Y')))
    if getattr(record, 'sale_code', ''):
        out.append(('sale', f'Sale code {record.sale_code}'))
    return out


def assembly_status(assembly):
    if assembly.deprecated:
        return Status('Deprecated', 'muted', [])
    if assembly.has_open_feedback:
        return Status('Needs review', 'bad', [])
    if not assembly.line_items.exists():
        return Status('Empty', 'warn', ['line items'])
    return Status('Complete', 'ok', [])


def _words(query):
    return [w for w in (query or '').split() if w][:8]


def parts(user, query='', which='all', page=1):
    """ A page of the user's parts matching `query` (every word in the reference, name or manufacturer)
    and the filter `which`, each row with its status. """
    rows = Part.all_available_to_user(user).select_related('team').prefetch_related('sources')
    for word in _words(query):
        rows = rows.filter(Q(reference__icontains=word) | Q(name__icontains=word) | Q(manufacturer__icontains=word))
    rows = rows.order_by('reference')
    which = which if which in FILTERS else 'all'
    items = [(part, part_status(part)) for part in rows]
    if which == 'attention':
        items = [item for item in items if item[1].needs_attention]
    elif which == 'missing':
        items = [item for item in items if item[1].is_missing]
    return Paginator(items, PAGE_SIZE).get_page(page)


def assemblies(user, query='', page=1):
    rows = SubAssembly.objects.filter(Q(team__in=user.team_set.all()) | Q(shared=True)).select_related('team', 'project')
    for word in _words(query):
        rows = rows.filter(Q(reference__icontains=word) | Q(name__icontains=word))
    rows = rows.order_by('-is_toplevel', 'reference')
    items = [(assembly, assembly_status(assembly)) for assembly in rows]
    return Paginator(items, PAGE_SIZE).get_page(page)


def assembly_tree(user, selected_id=None, query=''):
    """ The assemblies as a tree for the library: every top-level project as a root, its sub-assemblies
    beneath (by line items), then the assemblies in no project's tree. One query for the line items.
    With a `query`, only the branches that lead to a matching assembly are kept. Returns `(roots, orphans)`. """
    from bom.models import SubAssemblyLineItem
    rows = list(SubAssembly.objects.filter(Q(team__in=user.team_set.all()) | Q(shared=True))
                .select_related('pcbsubassembly').order_by('reference'))
    by_id = {assembly.id: assembly for assembly in rows}
    children = {}
    for line in SubAssemblyLineItem.objects.filter(subassembly__in=rows, child_subassembly__in=rows):
        children.setdefault(line.subassembly_id, []).append(line.child_subassembly_id)
    words = [w.lower() for w in _words(query)]

    def matches(assembly):
        text = f'{assembly.reference} {assembly.name}'.lower()
        return all(word in text for word in words)

    used = set()

    def node(assembly, trail):
        used.add(assembly.id)
        kids = [node(by_id[child], trail | {assembly.id}) for child in children.get(assembly.id, [])
                if child in by_id and child not in trail]
        kids = [kid for kid in kids if kid is not None]
        selected = assembly.id == selected_id
        if words and not matches(assembly) and not kids:
            return None
        return {'assembly': assembly, 'children': kids, 'selected': selected,
                'expanded': any(kid['selected'] or kid['expanded'] for kid in kids) or bool(words),
                'status': assembly_status(assembly)}

    roots = [node(assembly, set()) for assembly in rows if assembly.is_toplevel]
    orphans = [node(assembly, set()) for assembly in rows if assembly.id not in used and not assembly.is_toplevel]
    return [r for r in roots if r], [o for o in orphans if o]


def project_contents(project):
    """ Everything inside a project: the assemblies in its tree (the project first, then each level), and
    the parts those assemblies use, by reference. One query per level, never a loop per record. """
    from bom.models import SubAssemblyLineItem
    assemblies, seen, frontier = [], {project.id}, [project]
    while frontier:
        assemblies += frontier
        lines = SubAssemblyLineItem.objects.filter(subassembly__in=frontier, child_subassembly__isnull=False) \
            .select_related('child_subassembly')
        frontier = []
        for line in lines:
            if line.child_subassembly_id not in seen:
                seen.add(line.child_subassembly_id)
                frontier.append(line.child_subassembly)
    parts = Part.objects.filter(subassemblylineitem__subassembly__in=assemblies).distinct() \
        .prefetch_related('sources').order_by('reference')
    return assemblies, list(parts)
