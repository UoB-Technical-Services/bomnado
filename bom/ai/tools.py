""" The tool surface: what an AI may do in Bomnado, defined once and served two ways.

Each tool is a plain function taking a `ToolContext` (who is acting, for which team) and its
JSON-schema'd arguments, returning something JSON-serialisable (or `Blocks`, for files). The
same registry is handed to the in-app chat as Messages API tools (`bom.ai.chat`) and to
Claude Desktop / Claude Code as MCP tools (`bom.ai.mcp_server`), so both hosts see exactly
the same Bomnado.

Reads are bounded and compact (the model pays for every character). Writes go through
`bom.ai.actions`: as the user, validated, attributed in history, flagged for review.
"""
import json
from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.urls import reverse

from bom.ai import actions
from bom.ai.fetch import FetchError, UnsafeURL, fetch_url, html_to_text, page_hints, decode_body
from bom.models import Attachment, Feedback, NamedPiece, Part, PartSource, SubAssembly, SubAssemblyLineItem

""" Where searches stop, and how much of a page or a field a tool hands back. """
MAX_ROWS = 20
MAX_PAGE_TEXT = 30_000
MAX_FIELD = 4000
MAX_HISTORY = 20


@dataclass
class ToolContext:
    """ Who a tool call acts as. `origin` names the cause in history ("Chat: make it black");
    `attachments` are the files the person handed over (filename -> Attachment), available to
    `attach_file` / `create_part`; `touched` collects what was created or changed. """
    user: object
    team: object
    origin: str = 'AI chat'
    attachments: dict = field(default_factory=dict)
    touched: list = field(default_factory=list)

    def touch(self, record, what):
        item = {**actions.describe(record), 'what': what}
        if not any(t['model'] == item['model'] and t['id'] == item['id'] for t in self.touched):
            self.touched.append(item)


@dataclass
class Blocks:
    """ A tool result that is content blocks (an image, a PDF) rather than JSON. """
    blocks: list


class Tool:
    def __init__(self, name, description, schema, handler, writes):
        self.name, self.description, self.schema, self.handler, self.writes = name, description, schema, handler, writes

    def as_anthropic(self):
        return {'name': self.name, 'description': self.description, 'input_schema': self.schema}


TOOLS = {}


def tool(name, description, properties, required=(), writes=False):
    """ Register a tool. `properties` is the JSON-schema property map of its arguments. """
    schema = {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}

    def register(handler):
        TOOLS[name] = Tool(name, description, schema, handler, writes)
        return handler
    return register


def anthropic_tools():
    return [t.as_anthropic() for t in TOOLS.values()]


def call(ctx, name, arguments):
    """ Run a tool, never raising: problems come back as `{'error': ...}` for the model to read. """
    t = TOOLS.get(name)
    if t is None:
        return {'error': f'Unknown tool {name}.'}
    try:
        return t.handler(ctx, **_arguments(t, arguments))
    except (LookupError, ValueError, TypeError) as error:
        return {'error': str(error)}
    except ValidationError as error:
        return {'error': 'Not saved: ' + '; '.join(actions.problems_of(error))}
    except PermissionDenied as error:
        return {'error': str(error)}
    except (UnsafeURL, FetchError) as error:
        return {'error': f'Could not fetch that: {error}'}


def _arguments(t, arguments):
    """ Only the arguments the tool knows, with required ones present. """
    known = t.schema['properties']
    given = {key: value for key, value in (arguments or {}).items() if key in known}
    missing = [key for key in t.schema['required'] if key not in given]
    if missing:
        raise ValueError(f'{t.name} needs {", ".join(missing)}.')
    return given


def to_text(result):
    """ A tool result as the text a tool_result block carries. """
    return result if isinstance(result, str) else json.dumps(result, default=str)


# --- argument schemas ------------------------------------------------------------------------

STR = {'type': 'string'}
NUM = {'type': 'number'}
INT = {'type': 'integer'}
BOOL = {'type': 'boolean'}


def s(description, **extra):
    return {'type': 'string', 'description': description, **extra}


def n(description, **extra):
    return {'type': 'number', 'description': description, **extra}


def i(description, **extra):
    return {'type': 'integer', 'description': description, **extra}


PART_PROPERTIES = {
    'reference': s('Uppercase letters, digits, dashes, dots inside; per the naming guide. e.g. M8-20MM-BOLT-BTN-BZP'),
    'name': s('Short, specific, for humans. e.g. "M8 x 20mm button head screw, BZP"'),
    'manufacturer': STR,
    'nature': s('S = standard off-the-shelf (default), B = bespoke / made to order', enum=['S', 'B']),
    'kgs': n('Weight of one unit in kilograms'),
    'dimensions': s('Outer bounding box only, in mm, exactly "L x W x H" (e.g. "120 x 80 x 25"). Nothing else '
                    'goes here; a cable length or thread size belongs in the spec'),
    'colour': s('Colour or finish, e.g. BZP, Black, RAL7035'),
    'spec': s('The specification as markdown: what it is, materials, ratings, standards'),
    'qc_steps': s('Incoming-goods checks, one per line as a markdown task list: "- [ ] Thread gauge fits"'),
    'hs_code': s('Customs commodity code, digits only'),
    'sale_code': STR,
}
SUPPLIER_PROPERTIES = {
    'supplier': s('Supplier name, e.g. RS, Farnell, Shop4Fasteners, Amazon'),
    'url': s('Link straight to the product page (a real one you fetched or found, never guessed)'),
    'partcode': s("The supplier's own part number / SKU / ASIN"),
    'rrp': n('Unit price excluding VAT, in the page currency, for ONE unit (pack price / pack size). Always give '
             'it when the page shows a price (see fetch_page prices); a supplier without a price is of little use'),
    'shipping': n('Typical shipping cost for a minimum order, excluding VAT. Left out = estimated from the '
                  "team's other purchases from this supplier"),
    'minimum_order': i('Smallest quantity that can be ordered (a pack of 100 = 100)'),
    'lead_time': i("Business days to arrive. Left out = estimated from the team's other purchases from this supplier, else 7"),
    'order_notes': s('Anything the purchaser must know. Markdown'),
}
ASSEMBLY_PROPERTIES = {
    'reference': s('Uppercase letters, digits and dashes'),
    'name': STR,
    'revision': s('Semantic version, e.g. 0.1.0'),
    'spec': s('High-level description. Markdown'),
    'instructions': s('Assembly instructions. Markdown; refer to parts as `REFERENCE` in backticks'),
    'qc_steps': s('Checks before the assembly ships, as a markdown task list'),
    'production_phase': STR,
    'is_toplevel': {'type': 'boolean', 'description': 'A top-level product / project rather than a sub-assembly'},
    'project': s('The top-level assembly this belongs to: its reference or id'),
    'sale_code': STR,
    'hs_code': STR,
}
LINE_ITEM = {'type': 'object', 'properties': {
    'item': s('What goes in: a part or assembly reference, or "part:<id>" / "assembly:<id>"'),
    'quantity': i('How many (default 1)'), 'notes': STR}, 'required': ['item'], 'additionalProperties': False}
RECORD = s('A part or assembly: its reference, or "part:<id>" / "assembly:<id>"')


# --- reading ---------------------------------------------------------------------------------

def _user_teams(ctx):
    return ctx.user.team_set.all()


def _words(query):
    return [w for w in (query or '').replace(',', ' ').split() if w]


def _part_row(part):
    return {'id': part.id, 'reference': part.reference, 'name': part.name, 'manufacturer': part.manufacturer,
            'nature': part.nature, 'dimensions': part.dimensions, 'colour': part.colour,
            'spec': (part.spec or '')[:160],
            'suppliers': [_source_short(src) for src in part.sources.all()[:3]]}


def _source_short(src):
    return {'id': src.id, 'supplier': src.source, 'partcode': src.partcode, 'rrp': src.rrp}


def _source_row(src):
    return {'id': src.id, 'supplier': src.supplier, 'url': src.url, 'partcode': src.partcode, 'rrp': src.rrp,
            'shipping': src.shipping, 'minimum_order': src.minimum_order, 'lead_time': src.lead_time,
            'order_notes': src.order_notes}


def supplier_defaults(ctx, fields):
    """ Lead time and shipping for a new supplier row, when not given: what the team's other rows from the
    same supplier (by name, else by site) say - the commonest lead time, the median shipping. Returns the
    fields filled in, and a note per estimate. """
    from collections import Counter
    from statistics import median
    from urllib.parse import urlparse
    fields = dict(fields)
    notes = {}
    siblings = PartSource.objects.filter(part__team__in=_user_teams(ctx)).exclude(url='', supplier='')
    name = (fields.get('supplier') or '').strip()
    domain = urlparse(fields.get('url') or '').netloc.lower().removeprefix('www.')
    if name:
        siblings = siblings.filter(supplier__iexact=name)
    elif domain:
        siblings = siblings.filter(url__icontains=domain)
    else:
        return fields, notes
    rows = list(siblings.values_list('lead_time', 'shipping')[:200])
    label = name or domain
    if fields.get('lead_time') in (None, 0) and rows:
        lead_times = [lt for lt, _ in rows if lt and lt > 1]
        if lead_times:
            fields['lead_time'] = Counter(lead_times).most_common(1)[0][0]
            notes['lead_time'] = f'{fields["lead_time"]} days, estimated from {len(lead_times)} other {label} rows'
    if fields.get('shipping') in (None, 0) and rows:
        shipping = [sh for _, sh in rows if sh]
        if shipping:
            fields['shipping'] = round(float(median(shipping)), 2)
            notes['shipping'] = f'{fields["shipping"]}, the median of {len(shipping)} other {label} rows'
    return fields, notes


def part_summary(part):
    """ Everything about a part the model may need, bounded. """
    used_in = SubAssemblyLineItem.objects.filter(child_part=part).select_related('subassembly')
    return {
        'id': part.id, 'reference': part.reference, 'name': part.name, 'manufacturer': part.manufacturer,
        'nature': part.nature, 'kgs': part.kgs, 'dimensions': part.dimensions, 'colour': part.colour,
        'spec': (part.spec or '')[:MAX_FIELD], 'qc_steps': (part.qc_steps or '')[:MAX_FIELD],
        'hs_code': part.hs_code, 'sale_code': part.sale_code, 'has_picture': bool(part.picture),
        'deprecated': bool(part.deprecated), 'team': part.team.name if part.team_id else '',
        'suppliers': [_source_row(src) for src in part.sources.all()],
        'named_pieces': [{'suffix': p.suffix, 'note': p.note} for p in part.named_pieces.all()],
        'attachments': [{'id': a.id, 'filename': a.filename} for a in Attachment.objects.attachments_for_object(part)],
        'used_in': [{'assembly': li.subassembly.reference, 'id': li.subassembly_id, 'quantity': li.quantity}
                    for li in used_in[:MAX_ROWS] if li.subassembly_id],
        'open_feedback': [{'by': _person(f.author), 'text': f.text[:300]} for f in Feedback.objects.open_for(part)],
        'updated': part.updated.isoformat(timespec='minutes'),
        'url': reverse('bom:part_editor_update', kwargs={'pk': part.id}),
    }


def _line_item(li):
    child = li.child_part or li.child_subassembly
    kind = 'part' if li.child_part_id else 'assembly'
    return {'id': li.id, 'item': f'{kind}:{child.pk}', 'reference': child.reference, 'name': child.name,
            'quantity': li.quantity, 'notes': li.notes}


def assembly_summary(assembly, depth=1):
    summary = {
        'id': assembly.id, 'reference': assembly.reference, 'name': assembly.name, 'revision': assembly.revision,
        'is_toplevel': assembly.is_toplevel, 'production_phase': assembly.production_phase,
        'project': assembly.project.reference if assembly.project_id else '',
        'spec': (assembly.spec or '')[:MAX_FIELD], 'instructions': (assembly.instructions or '')[:MAX_FIELD],
        'qc_steps': (assembly.qc_steps or '')[:MAX_FIELD], 'has_picture': bool(assembly.picture),
        'team': assembly.team.name if assembly.team_id else '',
        'line_items': [_line_item(li) for li in assembly.line_items.select_related('child_part', 'child_subassembly')
                       if li.child_part_id or li.child_subassembly_id],
        'attachments': [{'id': a.id, 'filename': a.filename}
                        for a in Attachment.objects.attachments_for_object(assembly)],
        'open_feedback': [{'by': _person(f.author), 'text': f.text[:300]}
                          for f in Feedback.objects.open_for(assembly)],
        'updated': assembly.updated.isoformat(timespec='minutes'),
        'url': reverse('bom:assembly_editor_update', kwargs={'pk': assembly.id}),
    }
    if depth > 1:
        for item in summary['line_items']:
            if item['item'].startswith('assembly:'):
                item['children'] = assembly_summary(SubAssembly.objects.get(pk=item['item'][9:]), depth - 1)['line_items']
    return summary


def _person(user):
    if user is None:
        return ''
    return user.first_name or user.email or user.username


@tool('search_parts',
      "Search the team's parts by words in the reference, name, manufacturer or spec (all words must match). "
      'Always search before creating a part: the same thing may already exist under another name.',
      {'query': s('Words to look for, e.g. "M8 nut" or a manufacturer number'), 'limit': i('Up to 50, default 20')},
      required=['query'])
def search_parts(ctx, query, limit=MAX_ROWS):
    rows = Part.objects.filter(team__in=_user_teams(ctx))
    for word in _words(query)[:8]:
        rows = rows.filter(Q(reference__icontains=word) | Q(name__icontains=word) | Q(manufacturer__icontains=word)
                           | Q(spec__icontains=word))
    rows = rows.order_by('reference')[:max(1, min(50, int(limit or MAX_ROWS)))]
    return [_part_row(p) for p in rows]


@tool('get_part', 'Everything about one part: fields, suppliers, named pieces, attachments, where it is used, '
                  'open feedback.', {'part': s('Reference or id')}, required=['part'])
def get_part(ctx, part):
    return part_summary(actions.find_part(part, ctx.user))


@tool('search_assemblies', "Search the team's assemblies by words in the reference or name.",
      {'query': STR, 'limit': i('Up to 50, default 20')}, required=['query'])
def search_assemblies(ctx, query, limit=MAX_ROWS):
    rows = SubAssembly.objects.filter(team__in=_user_teams(ctx))
    for word in _words(query)[:8]:
        rows = rows.filter(Q(reference__icontains=word) | Q(name__icontains=word))
    rows = rows.order_by('reference')[:max(1, min(50, int(limit or MAX_ROWS)))]
    return [{'id': a.id, 'reference': a.reference, 'name': a.name, 'revision': a.revision,
             'is_toplevel': a.is_toplevel, 'project': a.project.reference if a.project_id else ''} for a in rows]


@tool('get_assembly', 'An assembly with its line items (the bill of materials), one level deep unless `depth` says more.',
      {'assembly': s('Reference or id'), 'depth': i('Levels of sub-assemblies to expand, 1-3')}, required=['assembly'])
def get_assembly(ctx, assembly, depth=1):
    return assembly_summary(actions.find_assembly(assembly, ctx.user), depth=max(1, min(3, int(depth or 1))))


@tool('get_history', 'What changed on a part or assembly recently: when, by whom, why, which fields.',
      {'record': RECORD, 'limit': i('Entries, default 20')}, required=['record'])
def get_history(ctx, record, limit=MAX_HISTORY):
    obj = find_record(ctx, record)
    entries = []
    for entry in obj.history.all()[:max(1, min(50, int(limit or MAX_HISTORY)))]:
        previous = entry.prev_record
        changes = []
        if previous is not None:
            for change in entry.diff_against(previous).changes:
                changes.append({'field': change.field, 'from': str(change.old)[:120], 'to': str(change.new)[:120]})
        entries.append({'when': entry.history_date.isoformat(timespec='minutes'), 'by': _person(entry.history_user),
                        'type': {'+': 'created', '~': 'changed', '-': 'deleted'}.get(entry.history_type, '?'),
                        'reason': entry.history_change_reason or '', 'changes': changes})
    return entries


@tool('fetch_page', 'Read a public web page (a supplier product page, a datasheet PDF) as text, with the prices, '
                    'part numbers and availability found in its structured data and the pictures it shows. Use it '
                    'to get prices, part numbers and specifications from a link. Never guess a URL: find the real '
                    'page with web_search first. If it fails (403, 404), try web_fetch; if that fails too, give '
                    'the person the link so they can look themselves, and leave the price empty.',
      {'url': STR}, required=['url'])
def fetch_page(ctx, url):
    final_url, content_type, body = fetch_url(url)
    if 'pdf' in content_type.lower() or body[:5] == b'%PDF-':
        return Blocks([{'type': 'text', 'text': f'PDF from {final_url}:'}, _document(body)])
    html = decode_body(body)
    text, pictures = html_to_text(html, final_url)
    return {'url': final_url, **page_hints(html, text), 'text': text[:MAX_PAGE_TEXT],
            'pictures': [{'url': p['url'], 'alt': p['alt']} for p in pictures[:15]]}


@tool('read_attachment', "Read a file attached to a part or assembly (from get_part / get_assembly), or one the "
                         'person dropped into this conversation, by id.',
      {'attachment_id': INT}, required=['attachment_id'])
def read_attachment(ctx, attachment_id):
    attachment = Attachment.objects.filter(pk=attachment_id).first()
    if attachment is None:
        raise LookupError(f'No attachment #{attachment_id}.')
    owner = attachment.content_object
    if hasattr(owner, 'can_access') and not owner.can_access(ctx.user):
        raise actions.NotAllowed('You do not have access to that file.')
    with attachment.attachment_file.open('rb') as fh:
        body = fh.read()
    return Blocks(file_blocks(attachment.filename, body))


def file_blocks(name, body):
    """ A file as Messages API content blocks: a PDF document, an image, or text. """
    import base64
    lower = name.lower()
    if lower.endswith('.pdf') or body[:5] == b'%PDF-':
        return [{'type': 'text', 'text': f'File: {name}'}, _document(body)]
    if lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
        extension = lower.rsplit('.', 1)[-1]
        media = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'}.get(extension, f'image/{extension}')
        return [{'type': 'text', 'text': f'File: {name}'},
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media,
                                             'data': base64.standard_b64encode(body).decode()}}]
    return [{'type': 'text', 'text': f'File: {name}\n\n' + body.decode('utf-8', errors='replace')[:60_000]}]


def _document(body):
    import base64
    return {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf',
                                           'data': base64.standard_b64encode(body).decode()}}


def find_record(ctx, text):
    """ "part:12", "assembly:3", or a reference (parts first). """
    text = str(text or '').strip()
    kind, _, rest = text.partition(':')
    if kind.lower() == 'part' and rest:
        return actions.find_part(rest, ctx.user)
    if kind.lower() in ('assembly', 'subassembly') and rest:
        return actions.find_assembly(rest, ctx.user)
    try:
        return actions.find_part(text, ctx.user)
    except LookupError:
        try:
            return actions.find_assembly(text, ctx.user)
        except LookupError:
            raise LookupError(f'No part or assembly called {text!r}.')


# --- writing ---------------------------------------------------------------------------------

def _team(ctx):
    if ctx.team is None or not ctx.team.can_access(ctx.user):
        raise PermissionDenied('You are not in a team that can hold this.')
    return ctx.team


@tool('create_part',
      'Create a part. Search first; reuse an existing part when it is the same thing. Follow the naming guide. '
      'Give suppliers when the material names them; never invent prices or part numbers. Name the files the person '
      'gave you that document this part in `files`; a photo becomes its picture.',
      {**PART_PROPERTIES,
       'picture_url': s('URL of the best product photo, if any'),
       'suppliers': {'type': 'array', 'items': {'type': 'object', 'properties': SUPPLIER_PROPERTIES,
                                                'additionalProperties': False}},
       'files': {'type': 'array', 'items': STR, 'description': 'Filenames from this conversation to attach'}},
      required=['reference', 'name'], writes=True)
def create_part(ctx, suppliers=None, files=None, picture_url=None, **fields):
    team = _team(ctx)
    reference = (fields.get('reference') or '').strip().upper()
    existing = Part.objects.filter(team=team, reference=reference).first()
    if existing is not None:
        return {'error': f'{reference} already exists (id {existing.id}). Use update_part, or a different reference.'}
    part = actions.fill(Part(team=team), fields, actions.PART_FIELDS)
    actions.save_as(part, ctx.user, ctx.origin)
    ctx.touch(part, 'created')
    notes = []
    for given in suppliers or []:
        given, estimated = supplier_defaults(ctx, given)
        source = actions.fill(PartSource(part=part), given, actions.SOURCE_FIELDS)
        if not actions.is_blank_source(source):
            actions.save_as(source, ctx.user, ctx.origin, review=False)
            notes += [f'{source.supplier or source.url}: {what} {note}' for what, note in estimated.items()]
            if not source.rrp:
                notes.append(f'{source.supplier or source.url}: no price - give the person the link to check')
    attached = _attach(ctx, part, files or [])
    if not part.picture and picture_url:
        notes.append('picture: ' + actions.picture_from_url(part, picture_url))
    result = part_summary(part)
    if attached:
        result['attached'] = attached
    if notes:
        result['notes'] = notes
    return result


@tool('update_part', 'Change fields of a part. Only the fields given change; everything else is kept.',
      {'part': s('Reference or id'), **PART_PROPERTIES, 'picture_url': s('Set the picture from this URL')},
      required=['part'], writes=True)
def update_part(ctx, part, picture_url=None, **fields):
    record = actions.find_part(part, ctx.user)
    if fields:
        actions.fill(record, fields, actions.PART_FIELDS)
        actions.save_as(record, ctx.user, ctx.origin)
    result = part_summary(record)
    if picture_url:
        result['notes'] = ['picture: ' + actions.picture_from_url(record, picture_url)]
        actions.ensure_review(record, ctx.user)
    ctx.touch(record, 'updated')
    return result


@tool('add_supplier', 'Add a supplier (where to buy it, at what price) to a part. A blank supplier row the part '
                      'already has is filled in rather than duplicated.',
      {'part': s('Reference or id'), **SUPPLIER_PROPERTIES}, required=['part'], writes=True)
def add_supplier(ctx, part, **fields):
    record = actions.find_part(part, ctx.user)
    source = None
    if fields.get('url'):
        source = record.sources.filter(url__iexact=fields['url'].rstrip('/')).first() \
            or record.sources.filter(url__iexact=fields['url']).first()
    if source is None:
        source = record.sources.filter(url='', partcode='', supplier='').first() or PartSource(part=record)
    fields, estimated = supplier_defaults(ctx, fields)
    actions.fill(source, fields, actions.SOURCE_FIELDS)
    actions.save_as(source, ctx.user, ctx.origin)
    ctx.touch(record, 'updated')
    result = _source_row(source)
    if estimated:
        result['estimated'] = estimated
    if not source.rrp:
        result['warning'] = 'No price. Tell the person, and give them the link to check themselves.'
    return result


@tool('update_supplier', "Change a part's supplier row (id from get_part). Only the fields given change.",
      {'supplier_id': INT, **SUPPLIER_PROPERTIES}, required=['supplier_id'], writes=True)
def update_supplier(ctx, supplier_id, **fields):
    source = PartSource.objects.filter(pk=supplier_id).select_related('part').first()
    if source is None:
        raise LookupError(f'No supplier #{supplier_id}.')
    actions.check_access(source.part, ctx.user)
    actions.fill(source, fields, actions.SOURCE_FIELDS)
    actions.save_as(source, ctx.user, ctx.origin)
    ctx.touch(source.part, 'updated')
    return _source_row(source)


@tool('add_named_piece', 'Name a piece of a part that instructions refer to but nobody buys separately (a cable in a '
                         'loom, the lid of a box). Written PART>PIECE.',
      {'part': s('Reference or id'), 'suffix': s('Uppercase letters, digits and dashes, e.g. LID'),
       'note': s('One line on what it is')}, required=['part', 'suffix'], writes=True)
def add_named_piece(ctx, part, suffix, note=''):
    record = actions.find_part(part, ctx.user)
    piece = actions.fill(NamedPiece(part=record), {'suffix': suffix, 'note': (note or '')[:200]}, ('suffix', 'note'))
    if record.named_pieces.filter(suffix=piece.suffix).exists():
        return {'error': f'{record.reference}>{piece.suffix} already exists.'}
    actions.save_as(piece, ctx.user, ctx.origin)
    ctx.touch(record, 'updated')
    return {'reference': f'{record.reference}{NamedPiece.SEPARATOR}{piece.suffix}', 'note': piece.note}


@tool('create_assembly', 'Create an assembly (a bill of materials) with its line items. Parts must exist: create '
                         'them first, or search for them.',
      {**ASSEMBLY_PROPERTIES, 'line_items': {'type': 'array', 'items': LINE_ITEM}},
      required=['reference', 'name'], writes=True)
def create_assembly(ctx, line_items=None, project=None, **fields):
    team = _team(ctx)
    reference = (fields.get('reference') or '').strip().upper()
    existing = SubAssembly.objects.filter(team=team, reference=reference).first()
    if existing is not None:
        return {'error': f'{reference} already exists (id {existing.id}). Use update_assembly or set_line_item.'}
    fields.setdefault('revision', '0.1.0')
    assembly = actions.fill(SubAssembly(team=team), fields, actions.ASSEMBLY_FIELDS)
    if project:
        assembly.project = actions.find_assembly(project, ctx.user)
    actions.save_as(assembly, ctx.user, ctx.origin)
    ctx.touch(assembly, 'created')
    problems = []
    for line in line_items or []:
        try:
            _set_line_item(ctx, assembly, line.get('item'), line.get('quantity', 1), line.get('notes', ''))
        except (LookupError, ValidationError, PermissionDenied) as error:
            problems.append(f'{line.get("item")}: {error}')
    result = assembly_summary(assembly)
    if problems:
        result['problems'] = problems
    return result


@tool('update_assembly', 'Change fields of an assembly. Only the fields given change.',
      {'assembly': s('Reference or id'), **ASSEMBLY_PROPERTIES}, required=['assembly'], writes=True)
def update_assembly(ctx, assembly, project=None, **fields):
    record = actions.find_assembly(assembly, ctx.user)
    actions.fill(record, fields, actions.ASSEMBLY_FIELDS)
    if project:
        record.project = actions.find_assembly(project, ctx.user)
    actions.save_as(record, ctx.user, ctx.origin)
    ctx.touch(record, 'updated')
    return assembly_summary(record)


@tool('set_line_item', "Add a part or assembly to an assembly's bill of materials, change its quantity or notes, "
                       'or remove it (quantity 0).',
      {'assembly': s('Reference or id'), **LINE_ITEM['properties']}, required=['assembly', 'item'], writes=True)
def set_line_item(ctx, assembly, item, quantity=1, notes=''):
    record = actions.find_assembly(assembly, ctx.user)
    outcome = _set_line_item(ctx, record, item, quantity, notes)
    return {'assembly': record.reference, **outcome}


def _set_line_item(ctx, assembly, item, quantity, notes):
    child = find_record(ctx, item)
    quantity = int(quantity if quantity is not None else 1)
    if isinstance(child, Part):
        line = assembly.line_items.filter(child_part=child).first()
    else:
        if child.pk == assembly.pk:
            raise ValueError('An assembly cannot contain itself.')
        line = assembly.line_items.filter(child_subassembly=child).first()
    if quantity < 1:
        if line is not None:
            line._change_reason = f'{ctx.origin} - {actions.ATTRIBUTION}'
            line._history_user = ctx.user
            line.delete()
            actions.ensure_review(assembly, ctx.user)
        ctx.touch(assembly, 'updated')
        return {'item': child.reference, 'removed': True}
    if line is None:
        line = SubAssemblyLineItem(subassembly=assembly)
        if isinstance(child, Part):
            line.child_part = child
        else:
            line.child_subassembly = child
    line.quantity = quantity
    if notes is not None:
        line.notes = notes
    actions.save_as(line, ctx.user, ctx.origin)
    ctx.touch(assembly, 'updated')
    return _line_item(line)


@tool('add_feedback', 'Leave a comment on a part or assembly for the team (a question, a note, something to check). '
                      'Not for describing your own changes: those are recorded automatically.',
      {'record': RECORD, 'text': s('Markdown')}, required=['record', 'text'], writes=True)
def add_feedback(ctx, record, text):
    obj = find_record(ctx, record)
    feedback = Feedback.objects.create(content_object=obj, text=(text or '').strip()[:4000], author=ctx.user)
    ctx.touch(obj, 'commented on')
    return {'id': feedback.id, 'on': obj.reference}


@tool('attach_file', 'Attach a file the person gave you in this conversation to a part or assembly. A photo becomes '
                     'the picture if there is none.',
      {'record': RECORD, 'filename': s('As listed in the conversation')}, required=['record', 'filename'], writes=True)
def attach_file(ctx, record, filename):
    obj = find_record(ctx, record)
    attached = _attach(ctx, obj, [filename])
    if not attached:
        raise LookupError(f'No file called {filename!r} in this conversation. Files: {", ".join(ctx.attachments) or "none"}.')
    actions.ensure_review(obj, ctx.user)
    ctx.touch(obj, 'updated')
    return {'attached': attached, 'to': obj.reference}


@tool('set_picture', "Set a part's or assembly's picture from a web URL or a file from this conversation.",
      {'record': RECORD, 'source': s('An image URL, or a filename from this conversation')},
      required=['record', 'source'], writes=True)
def set_picture(ctx, record, source):
    obj = find_record(ctx, record)
    attachment = _match_attachment(source, ctx.attachments)
    if attachment is not None:
        with attachment.attachment_file.open('rb') as fh:
            outcome = 'ok' if actions.picture_from_bytes(obj, fh.read()) else 'that file is not an image'
    elif source.lower().startswith('http'):
        outcome = actions.picture_from_url(obj, source)
    else:
        raise LookupError(f'{source!r} is neither a URL nor a file in this conversation.')
    actions.ensure_review(obj, ctx.user)
    ctx.touch(obj, 'updated')
    return {'picture': outcome, 'on': obj.reference}


def _attach(ctx, record, names):
    """ Attach the named conversation files to a record; the first image becomes its picture if it has none. """
    attached = []
    for name in names:
        attachment = _match_attachment(name, ctx.attachments)
        if attachment is None or attachment.filename in attached:
            continue
        copy, body = actions.attach_copy(record, attachment)
        attached.append(attachment.filename)
        if hasattr(record, 'picture') and not record.picture:
            actions.picture_from_bytes(record, body)
    return attached


def _match_attachment(name, attachments):
    """ The uploaded file a model-written name refers to: exact, by basename, or by stem ignoring
    the suffix storage adds to a clashing name (`loom_Ab3Xk9Q.pdf` for `loom.pdf`). """
    import re
    name = (name or '').strip()
    if not name:
        return None
    base = name.split('/')[-1]
    for candidate in (name, base):
        if candidate in attachments:
            return attachments[candidate]

    def stem(filename):
        stem, _, ext = filename.lower().rpartition('.')
        return re.sub(r'[\s_-]+', '', re.sub(r'_[a-z0-9]{7}$', '', stem or ext))

    wanted = stem(base)
    for stored, attachment in attachments.items():
        if stem(stored) == wanted:
            return attachment
    return None
