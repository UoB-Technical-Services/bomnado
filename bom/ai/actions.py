""" How AI output touches records: exactly as a person would, one record at a time.

Every write here goes through the model layer as the requesting user: `full_clean`, team
access checks, history with a reason naming where the change came from, and an open
Feedback on the record asking a human to review it. There is no plan, no dry run and no
approval step: the AI does what it was asked and the activity strip's Revert is the safety
net (see `bom.ai.tools`, which is the only caller).
"""
import io
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from PIL import Image

from bom.ai.fetch import FetchError, UnsafeURL, download_image
from bom.models import Attachment, Feedback, NamedPiece, Part, PartSource, SubAssembly, SubAssemblyLineItem

REVIEW_TEXT = 'Bomnado AI - requires human review.'
ATTRIBUTION = 'Bomnado AI'

""" The placeholder reference a blank part is born with (`get_default_reference`). """
AUTO_REFERENCE = re.compile(r'^[0-9A-F]{8}$')

PART_FIELDS = ('reference', 'name', 'manufacturer', 'nature', 'kgs', 'dimensions', 'colour', 'spec', 'qc_steps',
               'hs_code', 'sale_code')
ASSEMBLY_FIELDS = ('reference', 'name', 'revision', 'spec', 'instructions', 'qc_steps', 'production_phase',
                   'is_toplevel', 'sale_code', 'hs_code')
SOURCE_FIELDS = ('supplier', 'url', 'partcode', 'rrp', 'shipping', 'minimum_order', 'lead_time', 'order_notes')


class NotAllowed(PermissionDenied):
    """ The user may not touch that record. """


def check_access(record, user):
    if record is None or not record.can_access(user):
        raise NotAllowed('You do not have access to that record.')
    return record


def save_as(record, user, origin, review=True):
    """ Validate and save `record` as `user`, with history attributed to the AI and (for the
    records people review) one open review comment. Raises `ValidationError`. """
    # Pictures are set separately; an assembly's project is optional in the database, if not on the form.
    exclude = [name for name in ('picture', 'project') if hasattr(record, name)]
    record.full_clean(exclude=exclude)
    record._change_reason = f'{origin} - {ATTRIBUTION}'[:100]
    record._history_user = user  # no request middleware here: say who it was
    record.save()
    if review:
        ensure_review(record, user)
    return record


def ensure_review(record, user, note=''):
    """ One open "requires human review" comment per record, however many changes the AI makes. """
    target = record
    if isinstance(record, (PartSource, NamedPiece)):
        target = record.part
    elif isinstance(record, SubAssemblyLineItem):
        target = record.subassembly
    if not Feedback.objects.open_for(target).filter(text__startswith=REVIEW_TEXT).exists():
        Feedback.objects.create(content_object=target, text=REVIEW_TEXT + (f'\n\n{note}' if note else ''), author=user)


DIMENSION_NUMBER = r'(\d+(?:\.\d+)?)\s*(?:mm)?'
DIMENSIONS = re.compile(r'^\s*' + DIMENSION_NUMBER + r'\s*[x×X*]\s*' + DIMENSION_NUMBER
                        + r'(?:\s*[x×X*]\s*' + DIMENSION_NUMBER + r')?\s*(?:mm)?\s*$')


def normalise_dimensions(text):
    """ `dimensions` is the outer box in mm as "L x W x H" and nothing else: "120x80x25mm" and
    "120 × 80 × 25" become "120 x 80 x 25"; "2m cable" or "M8" become '' (the spec is the place for those). """
    match = DIMENSIONS.match(text or '')
    if not match:
        return ''
    numbers = [n for n in match.groups() if n]
    numbers = [n[:-2] if n.endswith('.0') else n for n in numbers]
    return ' x '.join(numbers)


def as_checklist(text):
    """ Quality-control steps as a markdown task list: plain bullets become `- [ ]` items. """
    lines = []
    for line in (text or '').split('\n'):
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]
        if stripped[:2] in ('- ', '* ') and not stripped[2:].startswith('['):
            lines.append(f'{indent}- [ ] {stripped[2:]}')
        else:
            lines.append(line)
    return '\n'.join(lines)


def fill(record, fields, allowed):
    """ Apply the given fields (only those given) to a record, tidying the ones with a house style. """
    for name, value in fields.items():
        if name not in allowed or value is None:
            continue
        if name in ('reference', 'suffix') and isinstance(value, str):
            value = value.strip().upper()
        if name == 'dimensions':
            value = normalise_dimensions(value)
        if name == 'qc_steps':
            value = as_checklist(value)
        if name in ('minimum_order', 'lead_time'):
            value = max(1, int(value or 1))
        if name == 'supplier' and isinstance(value, str):
            value = value[:100]
        setattr(record, name, value)
    return record


def is_blank_source(source):
    return not (source.url or source.supplier or source.partcode or source.rrp)


def attach_copy(record, attachment):
    """ Attach a copy of an uploaded file to a record (the chat keeps its own). Returns the copy. """
    with attachment.attachment_file.open('rb') as fh:
        body = fh.read()
    copy = Attachment(content_object=record)
    copy.attachment_file.save(attachment.filename, ContentFile(body))
    return copy, body


def picture_from_bytes(record, body):
    """ Use `body` as the record's picture if it is an image. Returns whether it was. """
    try:
        with Image.open(io.BytesIO(body)) as image:
            with io.BytesIO() as output:
                image.convert('RGBA').save(output, format='PNG')
                record.picture.save('picture.png', ContentFile(output.getvalue()), save=False)
    except (OSError, ValueError):
        return False
    type(record).objects.filter(pk=record.pk).update(picture=record.picture.name)
    return True


def picture_from_url(record, url):
    """ Fetch a picture from the web for a record, if it is safe to. Returns what happened, in words. """
    try:
        content = download_image(url)
    except (UnsafeURL, FetchError, ValueError, OSError) as error:
        return f'the picture could not be fetched ({error})'
    if content is None:
        return 'that was not an image'
    record.picture.save('picture.png', content, save=False)
    type(record).objects.filter(pk=record.pk).update(picture=record.picture.name)
    return 'ok'


def problems_of(error):
    """ A `ValidationError` as "field: message" lines, for the model to read. """
    if hasattr(error, 'message_dict'):
        return [f'{name}: {"; ".join(messages)}' for name, messages in error.message_dict.items()]
    return list(error.messages)


def describe(record):
    return {'model': record._meta.model_name, 'id': record.pk, 'reference': getattr(record, 'reference', str(record))}


def find_part(ref_or_id, user, team=None):
    """ A part by id or reference the user can access, or raise `LookupError`. """
    return _find(Part, ref_or_id, user, team)


def find_assembly(ref_or_id, user, team=None):
    return _find(SubAssembly, ref_or_id, user, team)


def _find(model, ref_or_id, user, team):
    text = str(ref_or_id or '').strip()
    record = None
    if text.isdigit():
        record = model.objects.filter(pk=int(text)).first()
    if record is None and text:
        rows = model.objects.filter(reference__iexact=text)
        if team is not None:
            rows = rows.filter(team=team)
        record = rows.first()
    if record is None:
        raise LookupError(f'No {model._meta.verbose_name} called {text!r}.')
    if not record.can_access(user):
        raise NotAllowed(f'You do not have access to {record.reference}.')
    return record


__all__ = ['REVIEW_TEXT', 'ATTRIBUTION', 'AUTO_REFERENCE', 'PART_FIELDS', 'ASSEMBLY_FIELDS', 'SOURCE_FIELDS',
           'NotAllowed', 'check_access', 'save_as', 'ensure_review', 'normalise_dimensions', 'as_checklist', 'fill',
           'is_blank_source', 'attach_copy', 'picture_from_bytes', 'picture_from_url', 'problems_of', 'describe',
           'find_part', 'find_assembly', 'ValidationError']
