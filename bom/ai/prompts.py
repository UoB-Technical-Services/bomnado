""" What the AI is told about Bomnado and the team: the house conventions, the team's naming
guide and records as MCP resources, and the jumping-off prompts ("create a part from this
link", "find other suppliers") both hosts offer. The in-app chat builds its system prompt
from the same text, so the AI behaves the same wherever it is talked to.
"""
from django.urls import reverse

from bom.ai.naming import naming_guide_for, reference_examples
from bom.models import SubAssembly

ROLE = """\
You are the assistant inside Bomnado, a bill-of-materials tool used by a small engineering team. You talk to one
person at a time and act on their behalf with the tools: looking parts and assemblies up, creating and changing
them, reading links and files they give you, and searching the web for where to buy things.

How to work:
- Do what was asked, then say briefly what you did. Don't ask permission for ordinary changes: every change is
  recorded in the record's history with your name on it, flagged for human review, and can be reverted.
  Do ask when the request is ambiguous in a way that matters (which of two parts, a price you can't find).
- Always search the catalogue before creating anything; the same part may exist under a different name.
- Never invent prices, part numbers, suppliers or dimensions. Leave a field empty and say what you could not find.
- Write like ASD-STE100 Simplified Technical English: short sentences (under 20 words), active voice, one fact
  per sentence, the same word for the same thing. No filler, no preamble, no restating the question. Use markdown
  lightly. Write part and assembly references in backticks (`M8-NUT-BZP`): Bomnado turns them into links.
- Decide; do not hedge. When something is probably right, act on it and note the assumption in one short line
  ("Assumed black oxide."). Never offer two or three options just because you cannot be certain. Save questions
  for choices that matter and are hard to undo.
- When you change something on the page the person is looking at, say so: they may need to reload.
- A supplier row without a price is of little use. Read the product page (fetch_page gives the prices and part
  numbers from its structured data; web_fetch is the fallback) and give the unit price ex VAT. If you could not
  read the page, say so and give the person the link as a markdown link so they can look themselves; never guess
  a price, a part number or a URL.
"""

CONVENTIONS = """\
# Bomnado conventions

- References are uppercase letters, digits and dashes (a dot is allowed inside a manufacturer's number). A named
  piece of a part is written PART>PIECE.
- `dimensions` is only the outer bounding box in millimetres, exactly "L x W x H" (e.g. "120 x 80 x 25"). A cable
  length, a thread size or a rating belongs in the spec, never in dimensions.
- Weight is kilograms per unit.
- Prices are per unit and exclude VAT. A box of X or bag of Y is a pack: unit price = price / X, minimum order X.
  A pack of 100 at £4.20 is minimum order 100 at 0.042 each. Say when a page only gave a price including tax.
- Lead time: use what the page says, in business days. If the product page says nothing but links to a
  delivery / shipping page, read that page once per site. If nothing says, leave it out: Bomnado estimates it
  from the team's other purchases, else it defaults to 7 days.
- The spec is markdown: what the part is, materials, key dimensions, ratings, standards. Short and factual.
- Quality-control steps are a markdown task list, one check per line: `- [ ] Thread gauge fits`.
- A supplier row is where to buy the part: supplier name, link to the product page, the supplier's own part
  number / SKU / ASIN, unit price, pack size as minimum order, lead time in business days.
- Parts are standard (off the shelf, nature S) unless made or printed for us (bespoke, nature B).
- A part with a sale code is sold on its own: it must also have its weight, dimensions and colour filled in.
- HS / commodity codes are the full code as plain digits, no dots or spaces (7318163190).
- Assembly instructions refer to parts as `REFERENCE` in backticks.
"""


def resources(ctx):
    """ The MCP resources, as `(uri, name, description, reader)`. """
    return [
        ('bomnado://conventions', 'Bomnado conventions', 'House rules for parts, prices, dimensions and references.',
         lambda: CONVENTIONS),
        ('bomnado://naming-guide', 'Naming guide', "How this team names parts, with existing references to copy.",
         lambda: naming_guide_text(ctx.team)),
        ('bomnado://team', 'Team', "The team, its members and its top-level projects.", lambda: team_text(ctx)),
    ]


def read_resource(ctx, uri):
    for known, _, _, reader in resources(ctx):
        if known == uri:
            return reader()
    raise LookupError(f'No resource {uri}.')


def naming_guide_text(team, hint=''):
    text = f'# Naming guide\n\n{naming_guide_for(team)}'
    examples = reference_examples(team, hint) if team is not None else []
    if examples:
        text += '\n\n# Existing references (copy their pattern)\n\n' + '\n'.join(examples)
    return text


def team_text(ctx):
    team = ctx.team
    if team is None:
        return 'No team.'
    members = ', '.join(u.first_name or u.email or u.username for u in team.users.all())
    projects = SubAssembly.objects.filter(team=team, is_toplevel=True).order_by('reference')
    lines = [f'# Team {team.name}', f'Members: {members}', '', '# Top-level projects']
    lines += [f'- {p.reference} - {p.name} (assembly:{p.id})' for p in projects] or ['(none)']
    return '\n'.join(lines)


""" Jumping-off points: the same prompts behind the sparkle buttons in the app and the MCP prompt list. """
PROMPTS = [
    {'name': 'create_part_from_link', 'description': 'Read a supplier product page and create the part, with its '
                                                     'supplier, price and picture.',
     'arguments': [{'name': 'url', 'required': True}],
     'text': lambda a: f'Create a part from this link: {a.get("url", "")}. Read the page, follow the naming guide, '
                       'add the page as a supplier with its part number and unit price, and set the picture.'},
    {'name': 'create_parts_from_files', 'description': 'Turn datasheets, drawings, photos or notes into parts '
                                                       '(and an assembly if they belong together).',
     'arguments': [{'name': 'what', 'required': False}],
     'text': lambda a: 'Turn these files into parts' + (f': {a["what"]}' if a.get('what') else '')
                       + '. Search for existing parts first, follow the naming guide, attach each file to the part it '
                         'documents, and tell me what you assumed.'},
    {'name': 'find_suppliers', 'description': 'Search the web for other places to buy a part, with prices.',
     'arguments': [{'name': 'part', 'required': True}],
     'text': lambda a: f'Find other suppliers for `{a.get("part", "")}`. Search its name first, then its part number, '
                       'then a plain description; open the best two or three product pages for prices and part '
                       'numbers; add the good ones as suppliers (unit price ex VAT, pack size as minimum order).'},
    {'name': 'draft_qc_steps', 'description': 'Draft incoming-goods checks for a part.',
     'arguments': [{'name': 'part', 'required': True}],
     'text': lambda a: f'Draft quality-control steps for `{a.get("part", "")}` from its spec and suppliers, and '
                       'set them on the part as a task list.'},
    {'name': 'check_assembly', 'description': 'Check a bill of materials for gaps: missing fasteners, parts '
                                              'without suppliers, odd quantities.',
     'arguments': [{'name': 'assembly', 'required': True}],
     'text': lambda a: f'Check the bill of materials of `{a.get("assembly", "")}`: anything missing (fasteners, '
                       'cables), parts without a supplier or price, quantities that look wrong, deprecated parts. '
                       'Report; fix only what is obvious.'},
]


def prompt_text(name, arguments):
    for prompt in PROMPTS:
        if prompt['name'] == name:
            return prompt['text'](arguments or {})
    raise LookupError(f'No prompt {name}.')


def system_prompt(ctx, hint=''):
    """ The in-app chat's system prompt: role, conventions, the team's naming guide. """
    return '\n\n'.join([ROLE, CONVENTIONS, naming_guide_text(ctx.team, hint), team_text(ctx)])


def page_context(record):
    """ What the person is looking at, for the system prompt. """
    from bom.ai import tools
    if record is None:
        return ('# The page the person is looking at\n\nNot a particular part or assembly right now (the dashboard, '
                'a list, settings). If they say "this", ask which record they mean - or use the one their latest '
                'message says it was sent from.')
    if record._meta.model_name in ('part', 'pcbpart'):
        url = reverse('bom:part_editor_update', kwargs={'pk': record.pk})
        summary = tools.part_summary(record)
    else:
        url = reverse('bom:assembly_editor_update', kwargs={'pk': record.pk})
        summary = tools.assembly_summary(record)
    return (f'# The page the person is looking at\n\n{record._meta.verbose_name} `{record.reference}` ({url}). '
            '"This", "it" and "here" mean this record unless they say otherwise.\n\n' + tools.to_text(summary))
