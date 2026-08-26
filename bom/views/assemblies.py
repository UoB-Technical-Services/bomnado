""" The assembly editor: creating, editing, line items, and the printable documentation view. """
import os
import re
from io import StringIO
import csv
from typing import List
from bom.types import KiCadBomRow

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST
from django.views.generic.base import TemplateView, RedirectView

from bom.forms import SubAssemblyForm, SubAssemblyItemFormset
from bom.models import Part, SubAssembly, SubAssemblyLineItem, Team, PCBPart, PCBSubAssembly, get_default_reference
from bom.views.shared import redirect_back_with_message


class AssemblyStartView(LoginRequiredMixin, View):
    """ The Assemblies tab: the first project's editor (the dashboard when there are none). """
    login_url = '/accounts/login/'

    def get(self, request, *args, **kwargs):
        first = SubAssembly.objects.filter(team__in=request.user.team_set.all()).order_by('-is_toplevel', 'reference').first()
        if first:
            return redirect(reverse_lazy('bom:assembly_editor_update', kwargs={'pk': first.id}))
        return redirect(reverse_lazy('bom:assembly_editor'))


class AssemblyEditorCreateView(LoginRequiredMixin, RedirectView):
    """ Used to create new assemblies. The given parameter is used
    as the REFERENCE name.
    """
    login_url = '/accounts/login/'

    def get_redirect_url(self, *args, **kwargs):

        def _redirect(part):
            return

        # Work out the reference we want to use.
        reference = self.request.POST.get('reference')
        reference = reference.strip().upper() if reference else None

        csv_file = self.request.FILES.get('csv_file')
        upload_action = self.request.POST.get('action') == 'upload'
        is_upload = upload_action or bool(csv_file)

        if not reference:
            # Use the helper function to set error message and determine redirect URL
            allowed_views = {
                'assembly_editor_update': ('bom:assembly_editor_update', 'pk'),
                'start': ('bom:start', None),
                'dashboard': ('bom:start', None),
            }
            return redirect_back_with_message(
                request=self.request,
                message="Project name is required.",
                message_key='error_message',
                default_url=reverse_lazy('bom:start'),
                allowed_views=allowed_views
            )

        if is_upload:
            if not csv_file:
                allowed_views = {
                    'assembly_editor_update': ('bom:assembly_editor_update', 'pk'),
                    'start': ('bom:start', None),
                    'dashboard': ('bom:start', None),
                }
                return redirect_back_with_message(
                    request=self.request,
                    message='Please select a KiCAD BOM CSV file to upload.',
                    message_key='pcb_upload_error',
                    default_url=reverse_lazy('bom:start'),
                    allowed_views=allowed_views
                )
            self.request.session['pcb_upload_message'] = f'Uploaded KiCAD BOM CSV file: {csv_file.name} ({csv_file.size} bytes)'
            self.request.session['pcb_upload_error'] = None
            # Attempt to parse the KiCAD BOM CSV and save rows to the session for follow-up processing.
            try:
                # Read bytes and decode, handling possible BOM
                raw = csv_file.read()
                if isinstance(raw, bytes):
                    text = raw.decode('utf-8-sig', errors='replace')
                else:
                    text = str(raw)

                fp = StringIO(text)
                reader = csv.DictReader(fp, delimiter=',', skipinitialspace=True)

                # Normalize header names by stripping whitespace
                headers = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []

                rows: List[KiCadBomRow] = []
                expected_keys = ['Reference', 'Footprint', 'Qty', 'Value', 'Manufacturer', 'LCSC', 'Supplier and ref']
                for r in reader:
                    if r is None:
                        continue
                    if not any(((v or '').strip() if isinstance(v, str) else v) for v in r.values()):
                        continue

                    # Normalize each row's keys to stripped header names and build a lowercase lookup
                    normalized = {(k.strip() if k else ''): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
                    lower_lookup = {(k.lower() if k else ''): v for k, v in normalized.items()}

                    # Build a TypedDict row with expected keys (case-insensitive lookup)
                    row_td: KiCadBomRow = {}
                    for key in expected_keys:
                        value = normalized.get(key)
                        if value is None:
                            value = lower_lookup.get(key.lower())
                        if value is None:
                            value = lower_lookup.get(key.lower().replace(' ', '_'))
                        if value is None:
                            value = ''

                        # Coerce Qty to int when possible
                        if key == 'Qty':
                            try:
                                row_td['Qty'] = int(value) if value != '' else 0
                            except Exception:
                                row_td['Qty'] = value
                        else:
                            row_td[key] = value

                    rows.append(row_td)

                # Save parsed CSV information into session for later processing steps.
                # Keep only simple serializable types (str/int).
                self.request.session['pcb_csv_headers'] = headers
                self.request.session['pcb_csv_rows'] = rows
            except Exception as e:
                # Record parse error for the user and clear any partial data
                self.request.session['pcb_upload_error'] = f'Failed to parse CSV file: {e}'
                self.request.session['pcb_csv_headers'] = []
                self.request.session['pcb_csv_rows'] = []

        # Work out project and owning team. If project is not set
        project_id = self.request.POST.get('project')
        team_id = self.request.POST.get('team')
        is_toplevel_str = self.request.POST.get('is_toplevel')

        # Process is_toplevel flag - make sure it's properly converted to boolean
        is_toplevel = False
        if is_toplevel_str == 'true' or is_toplevel_str == 'True' or is_toplevel_str == '1' or is_toplevel_str == 'on':
            is_toplevel = True

        # Handle team - required for all assemblies
        if team_id:
            team = Team.objects.get(id=team_id)
        else:
            # Default to user's first team
            team = self.request.user.team_set.first()

        # For top-level assemblies, project should be None
        project = None
        if project_id and not is_toplevel:
            project = SubAssembly.objects.get(id=int(project_id))
            team = project.team

        # If team is not set by now, malformed form
        if not team:
            raise ValueError('Team is not set')

        if not team.can_access(self.request.user):
            raise PermissionDenied('User does not have access to this team')

        # Create a new SubAssembly.
        try:
            # Create the assembly instance - if top-level, don't set project field
            AssemblyClass = PCBSubAssembly if is_upload else SubAssembly
            if is_toplevel:
                assembly = AssemblyClass(
                    reference=reference, name=reference, revision='0.0.1',
                    team=team, is_toplevel=True)
            else:
                assembly = AssemblyClass(
                    reference=reference, name=reference, revision='0.0.1',
                    project=project, team=team, is_toplevel=False)

            # Validate and save
            assembly.full_clean()
            assembly.save()
            # If this was an upload, process parsed CSV rows into PCBParts and line items.
            if is_upload:
                from django.db import transaction

                parsed_rows = self.request.session.get('pcb_csv_rows', []) or []
                created_parts = 0
                created_lines = 0
                errors = []

                with transaction.atomic():
                    for row_index, r in enumerate(parsed_rows, start=1):
                        # r is a KiCadBomRow TypedDict
                        raw_qty = r.get('Qty', 0) or 0
                        qty = 0
                        # Robust quantity parsing: handle ints, floats, commas, and whitespace
                        try:
                            if isinstance(raw_qty, int):
                                qty = raw_qty
                            else:
                                qs = str(raw_qty).strip().replace(',', '')
                                if qs == '':
                                    qty = 0
                                else:
                                    try:
                                        qty = int(qs)
                                    except ValueError:
                                        try:
                                            qty = int(float(qs))
                                        except Exception:
                                            qty = 0
                        except Exception:
                            qty = 0

                        reference_note = (r.get('Reference', '') or '')
                        value = (r.get('Value', '') or '')
                        manufacturer = (r.get('Manufacturer', '') or '')
                        footprint = (r.get('Footprint', '') or '')
                        lcsc = (r.get('LCSC', '') or '').strip()

                        # Use LCSC as the reference when available, otherwise derive
                        # a stable fallback from BOM data before using a generated id.
                        fallback_candidate = f"{footprint.strip()}-{value.strip()}".strip('-')
                        if not fallback_candidate or fallback_candidate == '-':
                            fallback_candidate = footprint.strip() or value.strip() or reference_note.strip()
                        candidate = lcsc if lcsc else (fallback_candidate or get_default_reference())

                        # Sanitize to allowed characters for Part.reference (uppercase, digits, dash)
                        cand = re.sub('[^0-9A-Za-z-]', '-', candidate).upper()
                        cand = re.sub('-+', '-', cand).strip('-')
                        if not cand:
                            cand = get_default_reference()

                        # Prefer an existing PCBPart by LCSC number when available.
                        pcb_part = None
                        if lcsc:
                            pcb_part = PCBPart.objects.filter(LCSCPartNo=lcsc, team=team).first()
                        if not pcb_part:
                            pcb_part = PCBPart.objects.filter(reference=cand, team=team).first()
                        if not pcb_part:
                            try:
                                pcb_part = PCBPart.objects.create(
                                    reference=cand,
                                    name=(value or cand),
                                    team=team,
                                    manufacturer=manufacturer,
                                    LCSCPartNo=lcsc,
                                    Footprint=footprint,
                                    Value=value,
                                )
                                created_parts += 1
                            except Exception as e:
                                errors.append({'row': row_index, 'data': r, 'reason': f'failed to create PCBPart: {e}'})
                                continue
                        else:
                            if lcsc and not pcb_part.LCSCPartNo:
                                pcb_part.LCSCPartNo = lcsc
                            if manufacturer:
                                pcb_part.manufacturer = manufacturer
                            pcb_part.Footprint = footprint
                            pcb_part.Value = value
                            pcb_part.save()

                        # Create the SubAssemblyLineItem for this row
                        try:
                            SubAssemblyLineItem.objects.create(subassembly=assembly, child_part=pcb_part, quantity=qty, notes=(reference_note.strip() if isinstance(reference_note, str) else reference_note))
                            created_lines += 1
                        except Exception as e:
                            errors.append({'row': row_index, 'data': r, 'reason': f'failed to create line item: {e}'})
                            # Skip invalid rows but continue processing remaining rows
                            continue

                # Clear parsed rows from session to avoid reprocessing
                try:
                    del self.request.session['pcb_csv_rows']
                    del self.request.session['pcb_csv_headers']
                except KeyError:
                    pass
                # Update upload message
                self.request.session['pcb_upload_message'] = f'Imported {created_lines} items and created {created_parts} parts.'
        except ValidationError as e:
            error_message_dict = e.message_dict

            # If it's a top-level assembly and the only error is the project field,
            # we can ignore that error and create the assembly directly
            if is_toplevel and len(error_message_dict) == 1 and 'project' in error_message_dict:
                assembly = SubAssembly(
                    reference=reference, name=reference, revision='0.0.1',
                    team=team, is_toplevel=True)
                assembly.save()
                return reverse_lazy('bom:assembly_editor_update', kwargs={'pk': assembly.id})

            # Handle other validation errors
            if 'reference' in error_message_dict:
                error_msg = error_message_dict['reference'][0]
            else:
                error_msg = "Project validation failed: " + ", ".join([f"{k}: {v[0]}" for k, v in error_message_dict.items()])

            # Use the helper function to set error message and determine redirect URL
            allowed_views = {
                'assembly_editor_update': ('bom:assembly_editor_update', 'pk'),
                'start': ('bom:start', None),
                'dashboard': ('bom:start', None),
            }
            return redirect_back_with_message(
                request=self.request,
                message=error_msg,
                message_key='error_message',
                default_url=reverse_lazy('bom:start'),
                allowed_views=allowed_views
            )

        # If we are inserting a parent, query for it and then create a line item for it.
        if self.request.POST.get('insert'):
            requested_parent = self.request.POST.get('parent')
            parent = SubAssembly.objects.get(id=requested_parent)
            try:
                SubAssemblyLineItem.objects.create(subassembly=parent, child_subassembly=assembly, quantity=1)
            except ValidationError as e:
                # Handle circular reference error
                if 'child_subassembly' in e.message_dict:
                    error_message = f"Circular reference detected: '{assembly.reference}' cannot be added to '{parent.reference}' as it would create a cycle in the assembly hierarchy."

                    # Use the standard feedback mechanism
                    allowed_views = {
                        'assembly_editor_update': ('bom:assembly_editor_update', 'pk'),
                        'start': ('bom:start', None),
                        'dashboard': ('bom:start', None),
                    }
                    return redirect_back_with_message(
                        request=self.request,
                        message=error_message,
                        message_key='error_message',
                        default_url=reverse_lazy('bom:start'),
                        allowed_views=allowed_views
                    )
                else:
                    # Handle other validation errors
                    error_msg = "Validation error: " + ", ".join([f"{k}: {v[0]}" for k, v in e.message_dict.items()])
                    allowed_views = {
                        'assembly_editor_update': ('bom:assembly_editor_update', 'pk'),
                        'start': ('bom:start', None),
                        'dashboard': ('bom:start', None),
                    }
                    return redirect_back_with_message(
                        request=self.request,
                        message=error_msg,
                        message_key='error_message',
                        default_url=reverse_lazy('bom:start'),
                        allowed_views=allowed_views
                    )

        return reverse_lazy('bom:assembly_editor_update', kwargs={'pk': assembly.id})


@login_required(login_url='/accounts/login/')
def AssemblyEditorUpdateView(request, pk):
    """ Process the form on the assembly editor page. Saves updates to
    assemblies and related line items.
    """
    assembly = get_object_or_404(SubAssembly, pk=pk)
    if not assembly.can_access(request.user):
        raise PermissionDenied('User does not have access to this Assembly')

    if request.method == 'POST':
        form = SubAssemblyForm(request.POST, request.FILES, instance=assembly)
        formset = SubAssemblyItemFormset(request.POST, request.FILES, instance=assembly)

        if form.is_valid() and formset.is_valid():
            try:
                form.save()
                formset.save()

                # Session storage converts to list, so must use list rather than tuple for comparison
                store_value = [assembly.id, assembly.reference]
                recent_assemblies = request.session.get('recent_assemblies', [])

                # Remove any existing entry for the same assembly ID, to prevent the same assembly appearing more than once
                recent_assemblies = [entry for entry in recent_assemblies if entry[0] != assembly.id]

                # Add the updated entry to the front of the list
                recent_assemblies.insert(0, store_value)

                # Ensure the list does not exceed the maximum allowed size
                if len(recent_assemblies) > settings.BOM_MAX_RECENT_ASSEMBLIES:
                    recent_assemblies = recent_assemblies[:settings.BOM_MAX_RECENT_ASSEMBLIES]

                request.session['recent_assemblies'] = recent_assemblies

                url = reverse_lazy('bom:assembly_editor_update', kwargs={'pk': pk})
                return HttpResponseRedirect(url)
            except ValidationError as e:
                # Handle circular reference error
                if 'child_subassembly' in e.message_dict:
                    error_message = e.message_dict['child_subassembly'][0]
                    # Get the problematic assembly name if possible
                    for form_item in formset:
                        if form_item.cleaned_data.get('child_subassembly') and not form_item.cleaned_data.get('DELETE'):
                            if form_item._errors and 'child_subassembly' in form_item._errors:
                                child_subassembly = form_item.cleaned_data.get('child_subassembly')
                                if child_subassembly:
                                    error_message = f"Circular reference detected: '{child_subassembly.reference}' would create a cycle in the assembly hierarchy. The assembly you're trying to add already contains this assembly or one of its parents."
                                    break

                    # Use the standard feedback mechanism
                    return redirect_back_with_message(
                        request=request,
                        message=error_message,
                        message_key="error_message",
                        default_url=reverse_lazy('bom:assembly_editor_update', kwargs={'pk': pk})
                    )
                else:
                    # Handle other validation errors
                    error_msg = "Validation error: " + ", ".join([f"{k}: {v[0]}" for k, v in e.message_dict.items()])
                    return redirect_back_with_message(
                        request=request,
                        message=error_msg,
                        message_key="error_message",
                        default_url=reverse_lazy('bom:assembly_editor_update', kwargs={'pk': pk})
                    )

    # process form data, redirect to success page
    else:
        form = SubAssemblyForm(instance=assembly)
        formset = SubAssemblyItemFormset(instance=assembly)

    # Build the tree to render. An assembly whose project has been deleted has no
    # project (SET_DEFAULT None) - show it as its own root rather than failing.
    root = assembly.project or assembly

    # Every line item in this team, grouped by parent assembly, in one query. Only
    # this team's assemblies can appear in the tree, so nothing else is loaded.
    # (`stylised_assembly` checks each node for a PCB sub-type, so that is joined too.)
    line_items_by_assy = dict()
    lines = SubAssemblyLineItem.objects.filter(
        subassembly__team=assembly.team, child_subassembly__isnull=False,
    ).select_related('child_subassembly', 'child_subassembly__pcbsubassembly')
    for line in lines:
        line_items_by_assy.setdefault(line.subassembly_id, []).append(line)

    # Collect assemblies used in the main product tree.
    used = set()

    # Output a node used to construct a PBS tree.
    def generate_node(assembly, level):
        used.add(assembly)
        return {
            'assembly': assembly,
            'level': level,
            'children': [],
            'selected': str(assembly.id) == str(pk),
            'expanded': False
        }

    # Traverse the PBS tree *without* querying the DB.
    def traverse(assembly, level):
        node = generate_node(assembly, level)
        children = [
            child.child_subassembly for child in line_items_by_assy.get(assembly.id, []) if child.child_subassembly
        ]
        for child in children:
            node['children'].append(traverse(child, level + 1))
        result = any(c['selected'] or c['expanded'] for c in node['children'])
        node['expanded'] = result
        return node

    # Compute the tree (note that we collect used items here).
    assembly_tree = traverse(root, 0)

    # Determine any objects that are not within the tree.
    orphans = root.children.exclude(id=root.id).exclude(id__in=[s.id for s in used]).select_related('pcbsubassembly')

    # Prepare template context.
    # Get any error messages from the session and add to context
    error_message = request.session.pop('error_message', None)
    pcb_upload_message = request.session.pop('pcb_upload_message', None)
    pcb_upload_error = request.session.pop('pcb_upload_error', None)

    context = {
        'form': form,
        'formset': formset,
        'assembly': assembly,
        'root': root,
        'tree': assembly_tree,
        'orphans': [traverse(orphan, 0) for orphan in orphans],
        'error_message': error_message,
        'pcb_upload_message': pcb_upload_message,
        'pcb_upload_error': pcb_upload_error,
    }
    return render(request, os.path.join('pages', 'assembly_editor.html'), context)


def render_assembly_line_items(request, assembly, error=None):
    """ The line-items fragment of the assembly editor (see `partial/assembly_line_items.html`).

    Returned by the htmx endpoints below so the browser swaps just the table,
    leaving the rest of the page - and the assembly tree - untouched.
    """
    context = {
        'assembly': assembly,
        'formset': SubAssemblyItemFormset(instance=assembly),
        'line_item_error': error,
    }
    return render(request, 'partial/assembly_line_items.html', context)


@login_required(login_url='/accounts/login/')
@require_POST
def assembly_line_item_add(request, pk):
    """ Add a part (`child_part`) or assembly (`child_subassembly`) to an assembly.

    Validation problems - including circular references - are reported inline
    in the returned fragment rather than as an error status, so htmx swaps the
    message into place.
    """
    assembly = get_object_or_404(SubAssembly, pk=pk)
    if not assembly.can_access(request.user):
        raise PermissionDenied('User does not have access to this Assembly')

    part_id = request.POST.get('child_part') or None
    subassembly_id = request.POST.get('child_subassembly') or None
    try:
        quantity = max(1, int(request.POST.get('quantity') or 1))
    except ValueError:
        quantity = 1

    # Only items the user can see may be inserted.
    child_part = child_subassembly = None
    if part_id:
        child_part = Part.all_available_to_user(request.user).filter(pk=part_id).first()
    elif subassembly_id:
        child_subassembly = SubAssembly.objects.filter(
            pk=subassembly_id, team__in=request.user.team_set.values_list('id')).first()
    if child_part is None and child_subassembly is None:
        return render_assembly_line_items(request, assembly, error='Choose a part or assembly to insert.')

    line = SubAssemblyLineItem(subassembly=assembly, child_part=child_part, child_subassembly=child_subassembly,
                               quantity=quantity)
    try:
        line.save()  # runs full_clean(), which rejects circular references
    except ValidationError as e:
        messages = e.message_dict.values() if hasattr(e, 'message_dict') else [e.messages]
        return render_assembly_line_items(request, assembly, error=' '.join(m for ms in messages for m in ms))

    return render_assembly_line_items(request, assembly)


@login_required(login_url='/accounts/login/')
@require_POST
def assembly_line_item_delete(request, pk, line_id):
    """ Remove a line item from an assembly and return the refreshed fragment. """
    assembly = get_object_or_404(SubAssembly, pk=pk)
    if not assembly.can_access(request.user):
        raise PermissionDenied('User does not have access to this Assembly')

    line = get_object_or_404(SubAssemblyLineItem, pk=line_id, subassembly=assembly)
    line.delete()
    return render_assembly_line_items(request, assembly)


class AssemblyDocumentationView(LoginRequiredMixin, TemplateView):
    """ View documentation for a given assembly. """
    login_url = '/accounts/login/'
    template_name = 'pages/assembly_viewer.html'

    @xframe_options_exempt
    def dispatch(self, request, *args, **kwargs):
        """ Check access.  Note: `xframe_options_exempt` to allow print iFrames without changing page. """
        pk = self.kwargs.get('pk')
        assembly = get_object_or_404(SubAssembly, pk=pk)
        if not assembly.can_access(request.user):
            raise PermissionDenied('User does not have access to this Assembly')
        return super(AssemblyDocumentationView, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(AssemblyDocumentationView, self).get_context_data(**kwargs)
        pk = self.kwargs.get('pk')
        assembly = get_object_or_404(SubAssembly, pk=pk)
        context['assembly'] = assembly
        return context
