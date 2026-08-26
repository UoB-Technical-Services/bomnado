""" The reference naming guide Claude follows, and the examples it is shown.

A team can write its own guide (`Team.naming_guide`); otherwise this default applies. It
started life as the rules in the Shop4Fasteners scraper, so fasteners come out exactly as
they always have.
"""
import re

from bom.models import Part

DEFAULT_NAMING_GUIDE = """\
References are UPPERCASE letters, digits and dashes, with a dot allowed inside a manufacturer's number
(`XB4-BA31.1`): no spaces, no other punctuation, no supplier names. Put the defining size first and the
finish or colour last. A named piece of a part is written `PART>PIECE` (e.g. `CHASSIS>LEGS`); never use `>`
in a reference itself.

Fasteners (metric):
- Bolts and screws: `M<size>-<length>MM-BOLT-<head>-<finish>`, head = BTN (button), HEX, RND (round / pan), CSNK (countersunk), SKT (socket cap). e.g. `M8-20MM-BOLT-BTN-BZP`, `M3-12MM-BOLT-CSNK-SELF-COLOUR`.
- Nuts: `M<size>-NUT-<finish>`, with the type before the finish when it matters: `M8-NUT-BZP`, `M8-NUT-NYLOC-BZP`.
- Washers: `M<size>-WASHER-<form>-<finish>`, form = FA (form A), FB (form B), LARGE-<outer diameter>MM (repair / penny), SPRING. e.g. `M8-WASHER-FA-BZP`, `M8-WASHER-LARGE-24MM-BZP`.
- Finishes: BZP (bright zinc plated), ZINC, BLACK, A2 / A4 (stainless), SELF-COLOUR, or a RAL code such as RAL7035.

Everything else:
- Start with what it is, then the defining dimensions or rating, then the material / finish: `ALU-EXTRUSION-2020-1000MM`, `BEARING-608-2RS`, `CABLE-USB-C-1M-BLACK`.
- Bespoke or printed parts: what it is, then the variant: `CHASSIS-PRINTED`, `BRACKET-LEFT`.
- If the page gives no way to name the part meaningfully, use the manufacturer's part number.
- Never invent a scheme that clashes with the existing references shown to you; copy their pattern.
"""


def naming_guide_for(team):
    """ The team's own guide, or the default. """
    return (getattr(team, 'naming_guide', '') or '').strip() or DEFAULT_NAMING_GUIDE


def reference_examples(team, text='', limit=40):
    """ Existing references Claude should copy the pattern of: anything sharing a metric size
    or a word with the page, topped up with the team's most recently touched parts. """
    parts = Part.objects.filter(team=team)
    examples = []
    tokens = set(re.findall(r'\bM\d+\b', text.upper()))
    tokens |= {word for word in re.findall(r'[A-Z]{4,}', text.upper())[:40]}
    if tokens:
        matching = parts.filter(reference__regex='|'.join(re.escape(token) for token in sorted(tokens)[:30]))
        examples += list(matching.order_by('-updated').values_list('reference', flat=True)[:limit // 2])
    recent = parts.exclude(reference__in=examples).order_by('-updated').values_list('reference', flat=True)
    examples += list(recent[:limit - len(examples)])
    return examples
