""" The activity strip on the part and assembly editors.

What happened to a record and the things that belong to it (a part's suppliers and
named pieces, an assembly's line items), newest first, merged with the feedback left
on it. Backed by django-simple-history: every save of a tracked model stores a full
copy of the row, and an entry here is the difference between two consecutive copies.

Only one page of entries is ever fetched (`PAGE_SIZE`, plus one to know whether there
is more); nothing here scans the database.
"""
import difflib
import os
from dataclasses import dataclass, field

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import Http404
from django.shortcuts import get_object_or_404

from bom import forms
from bom.models import (Feedback, NamedPiece, Part, PartSource, PCBPart, PCBSubAssembly, SubAssembly,
                        SubAssemblyLineItem)

""" Entries shown per page of the strip. """
PAGE_SIZE = 10

""" Bookkeeping columns that are never reported as a change. """
HIDDEN_FIELDS = {'id', 'created', 'updated', 'part_ptr', 'subassembly_ptr'}

""" What an editor page shows activity for: the page's own model (`self`), then the models that
belong to it, each with the column on its history rows that holds the page object's pk. """
SOURCES = {
    Part: [(Part, 'id'), (PCBPart, 'part_ptr_id'), (PartSource, 'part_id'), (NamedPiece, 'part_id')],
    SubAssembly: [(SubAssembly, 'id'), (PCBSubAssembly, 'subassembly_ptr_id'), (SubAssemblyLineItem, 'subassembly_id')],
}

""" Field labels, as the forms show them. Anything else falls back to the model field's name. """
LABELS = {
    Part: forms.PartCreationForm,
    SubAssembly: forms.SubAssemblyForm,
    PartSource: forms.PartSourceFormset.form,
    NamedPiece: forms.NamedPieceFormset.form,
    SubAssemblyLineItem: forms.SubAssemblyItemFormset.form,
}


@dataclass
class Change:
    """ One field that differs between two consecutive versions. """
    label: str
    old: str
    new: str
    diff: str = ''  # a unified diff for long text, in which case `old`/`new` are not shown inline


@dataclass
class Entry:
    """ One line of the strip. """
    kind: str                      # created | edited | deleted | feedback | resolved
    when: object                   # datetime
    user: object = None            # User, or None when not recorded
    is_self: bool = True           # about the page object itself (else about a child, see `target`)
    target: str = ''               # e.g. 'supplier rs-online.com' for a child
    changes: list = field(default_factory=list)
    reason: str = ''               # history change reason, e.g. a reference rename
    revert: tuple = None           # (historical model name, history_id) when the entry can be undone
    feedback: object = None        # the Feedback for feedback / resolved entries

    @property
    def summary(self):
        return ', '.join(change.label for change in self.changes)

    @property
    def is_revert(self):
        """ A change made by the Revert button (its reason says so). """
        return self.reason.startswith('Reverted')

    @property
    def icon(self):
        if self.is_revert:
            return 'revert'
        return {'created': 'add', 'edited': 'edit', 'deleted': 'remove'}.get(self.kind, self.kind)

    @property
    def verb(self):
        if self.is_revert:
            return {'created': 'restored', 'edited': 'reverted a change to',
                    'deleted': 'reverted the addition of'}[self.kind]
        if self.kind == 'created':
            return 'created' if self.is_self else 'added'
        return {'edited': 'changed', 'deleted': 'removed'}.get(self.kind, self.kind)


def base_model(obj):
    """ `Part` or `SubAssembly` for an instance of either (including the PCB subclasses). """
    if isinstance(obj, Part):
        return Part
    if isinstance(obj, SubAssembly):
        return SubAssembly
    raise TypeError(f'{obj!r} has no activity strip')


class _Lookup:
    """ Resolve a pk to the record's reference, remembering answers; `#pk` for anything gone. """

    def __init__(self):
        self.cache = {}

    def __call__(self, model, pk):
        if pk in (None, ''):
            return ''
        key = (model, pk)
        if key not in self.cache:
            found = model.objects.filter(pk=pk).values_list('reference', flat=True).first() \
                if 'reference' in [f.name for f in model._meta.fields] else None
            self.cache[key] = found if found is not None else f'#{pk}'
        return self.cache[key]


def tracked_fields(historical_model):
    """ The fields of a historical model that describe the record (not the history bookkeeping). """
    return [f for f in historical_model._meta.fields
            if f.name not in HIDDEN_FIELDS and not f.name.startswith('history')]


def _display(field_, value, lookup):
    """ A value as the strip shows it. """
    if value in (None, ''):
        return ''
    if field_.is_relation:
        return lookup(field_.related_model, value)
    if isinstance(field_, models.BooleanField):
        return 'Yes' if value else 'No'
    if isinstance(field_, models.DateTimeField):
        return value.strftime('%Y-%m-%d')
    if isinstance(field_, models.FileField):
        return os.path.basename(str(value))
    if field_.choices:
        return str(dict(field_.choices).get(value, value))
    return str(value)


def _labels(model):
    form = LABELS.get(model)
    return (form._meta.labels or {}) if form is not None else {}


def _changes(model, previous, record, lookup):
    """ The fields that differ between two consecutive versions of a record. """
    labels = _labels(model)
    changes = []
    for f in tracked_fields(type(record)):
        old, new = getattr(previous, f.attname), getattr(record, f.attname)
        if old == new:
            continue
        old_s, new_s = _display(f, old, lookup), _display(f, new, lookup)
        if old_s == new_s:
            continue
        label = labels.get(f.name) or str(f.verbose_name).replace('_', ' ').capitalize()
        is_long = isinstance(f, models.TextField) and (
            '\n' in old_s or '\n' in new_s or len(old_s) > 60 or len(new_s) > 60)
        if is_long:
            lines = difflib.unified_diff(old_s.splitlines(), new_s.splitlines(), lineterm='', n=1)
            changes.append(Change(label, old_s, new_s, diff='\n'.join(list(lines)[2:])))
        else:
            changes.append(Change(label, old_s, new_s))
    return changes


def _target(model, record, lookup):
    """ How a child record is named in the strip. """
    if model is PartSource:
        return f'supplier {PartSource(url=record.url).source or record.partcode or "#" + str(record.id)}'
    if model is NamedPiece:
        return f'named piece {lookup(Part, record.part_id)}{NamedPiece.SEPARATOR}{record.suffix}'
    if model is SubAssemblyLineItem:
        item = lookup(Part, record.child_part_id) if record.child_part_id \
            else lookup(SubAssembly, record.child_subassembly_id)
        return f'line item {record.quantity} × {item}'
    return ''


def _entry(model, is_self, record, previous, lookup):
    kind = {'+': 'created', '~': 'edited', '-': 'deleted'}[record.history_type]
    changes = _changes(model, previous, record, lookup) if kind == 'edited' and previous is not None else []
    if kind == 'edited' and not changes:
        return None  # a save that changed nothing shown here
    # The page object's own creation cannot be undone from its own page.
    revert = None if (is_self and kind == 'created') else (type(record).__name__, record.history_id)
    return Entry(kind=kind, when=record.history_date, user=record.history_user, is_self=is_self,
                 target='' if is_self else _target(model, record, lookup), changes=changes,
                 reason=record.history_change_reason or '', revert=revert)


def activity(obj, offset=0, limit=PAGE_SIZE):
    """ One page of the strip for `obj`: `(entries, has_more)`, newest first. """
    fetch = offset + limit + 1
    lookup = _Lookup()
    entries = []

    for model, key in SOURCES[base_model(obj)]:
        historical = model.history.model
        records = list(historical.objects.filter(**{key: obj.pk}).select_related('history_user')
                       .order_by('-history_date', '-history_id')[:fetch])
        for index, record in enumerate(records):
            # The version before this one: the next older row for the same record if it was
            # fetched, otherwise one query.
            previous = next((r for r in records[index + 1:] if r.id == record.id), None)
            if previous is None and record.history_type != '+':
                previous = record.prev_record
            entry = _entry(model, model in (Part, PCBPart, SubAssembly, PCBSubAssembly), record, previous, lookup)
            if entry is not None:
                entries.append(entry)

    feedback = Feedback.objects.for_object(obj).select_related('author', 'resolved_by')
    for item in feedback[:fetch]:
        entries.append(Entry(kind='feedback', when=item.created, user=item.author, feedback=item))
    for item in feedback.filter(resolved__isnull=False).order_by('-resolved')[:fetch]:
        entries.append(Entry(kind='resolved', when=item.resolved, user=item.resolved_by, feedback=item))

    entries.sort(key=lambda entry: entry.when, reverse=True)
    return entries[offset:offset + limit], len(entries) > offset + limit


def activity_context(obj, offset=0):
    """ Template context for `partial/activity.html` / `partial/activity_entries.html`. """
    entries, has_more = activity(obj, offset)
    model = base_model(obj)
    return {
        'obj': obj,
        'model_name': model._meta.model_name,
        'self_label': 'this part' if model is Part else 'this assembly',
        'entries': entries,
        'has_more': has_more,
        'offset': offset,
        'next_offset': offset + PAGE_SIZE,
        'open_feedback': Feedback.objects.open_for(obj).select_related('author').order_by('created'),
    }


def _apply(model, snapshot, reason, only=None):
    """ Make the live record look like `snapshot` (a historical row) - or just the fields in
    `only` - recreating the record if it is gone. Saved normally, so the change is itself
    recorded: nothing is ever lost. """
    live = model.objects.filter(pk=snapshot.id).first()
    if live is None:
        live, only = model(pk=snapshot.id), None
    for f in tracked_fields(type(snapshot)):
        if only is None or f.attname in only:
            setattr(live, f.attname, getattr(snapshot, f.attname))
    live._change_reason = reason
    live.save()
    return live


def revert(obj, historical_model_name, history_id):
    """ Undo the change an entry of `obj`'s strip describes.

    - an edit: the fields that edit changed go back to what they were before it (fields
      changed by later edits are left alone);
    - a removal: the record is recreated as it was;
    - an addition (of a child): the record is removed.
    """
    try:
        historical = apps.get_model('bom', historical_model_name)
    except LookupError:
        raise Http404(historical_model_name)
    model = getattr(historical, 'instance_type', None)
    sources = dict(SOURCES[base_model(obj)])
    if model not in sources:
        raise Http404(historical_model_name)
    record = get_object_or_404(historical, history_id=history_id, **{sources[model]: obj.pk})
    when = record.history_date.strftime('%d %b %Y %H:%M')

    if record.history_type == '+':
        if record.id == obj.pk and model in (Part, SubAssembly):
            raise PermissionDenied('The record cannot be removed from its own page.')
        live = model.objects.filter(pk=record.id).first()
        if live is not None:
            live._change_reason = f'Reverted the addition on {when}'
            live.delete()
    elif record.history_type == '-':
        _apply(model, record, f'Reverted the removal on {when}')
    else:
        previous = record.prev_record
        if previous is None:
            raise Http404('No earlier version to go back to.')
        changed = {f.attname for f in tracked_fields(historical)
                   if getattr(previous, f.attname) != getattr(record, f.attname)}
        _apply(model, previous, f'Reverted the change on {when}', only=changed)
