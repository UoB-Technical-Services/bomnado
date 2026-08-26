import base64
import datetime
import io
import os
import re
import uuid
import zipfile
from urllib.parse import urlparse
from collections import defaultdict, Counter
from io import StringIO
import csv
from typing import List
from bom.types import KiCadBomRow

import requests
from PIL import Image
from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import management
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db.models import Case, When, BooleanField, Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse, HttpResponseNotAllowed, \
    HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import Resolver404, reverse, reverse_lazy, resolve
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST
from django.views.generic.base import TemplateView, RedirectView

from bom.forms import PartCreationForm, PartSourceFormset, SubAssemblyForm, SubAssemblyItemFormset, AttachmentForm, \
    DealFormset, DealPartFormset, DealForm, UserAccountForm
from bom.models import Part, PartSource, SubAssembly, SubAssemblyLineItem, Attachment, Team, Deal, PCBPart, PCBSubAssembly, get_default_reference
from bom.scrapers.amazon import AmazonScrape
from bom.scrapers.rs import RSScrape
from bom.scrapers.shopfour import Shop4Scrape
from bom.utils import team_owner_required
from bom.utils.accounts import username_from_email
from bom.utils.export import is_superuser
from bom.utils.export.excel import export_database_to_excel, export_purchasing_spreadsheet

def get_path_from_referer(referer):
    """Extract the path from a referer URL using urlparse."""
    if referer:
        parsed_url = urlparse(referer)
        return parsed_url.path
    return referer


def redirect_back_with_message(
    request, message, message_key="error_message", default_url=None, namespace_check="bom", allowed_views=None
):
    """
    Helper function to set an error message and redirect back to the referrer page.

    Args:
        request: The Django request object
        message: The message to store in the session
        message_key: The session key to store the message under (defaults to 'error_message')
        default_url: The URL to redirect to if the referrer can't be resolved (defaults to 'bom:start')
        namespace_check: The namespace to check against resolved URLs (defaults to 'bom')
        allowed_views: A dictionary mapping view names to tuples of (url_name, kwarg_key) for redirection
                    Example: {'part_editor_update': ('bom:part_editor_update', 'pk')}

    Returns:
        A URL to redirect to
    """
    # Store the message in the session
    request.session[message_key] = message

    # If no allowed views are specified, use a default set
    if allowed_views is None:
        allowed_views = {
            "part_editor_update": ("bom:part_editor_update", "pk"),
            "assembly_editor_update": ("bom:assembly_editor_update", "pk"),
            "start": ("bom:start", None),
            "dashboard": ("bom:start", None),
        }

    # Get the default URL if not provided
    if default_url is None:
        default_url = reverse_lazy("bom:start")

    # Try to get and parse the referrer
    referer = request.META.get("HTTP_REFERER")
    if referer:
        try:
            path = get_path_from_referer(referer)
            resolved = resolve(path)

            # Check if we're coming from an allowed view in the specified namespace
            if resolved.namespace == namespace_check and resolved.url_name in allowed_views:
                url_name, kwarg_key = allowed_views[resolved.url_name]

                # If the view needs a parameter (e.g., pk), get it from the resolved kwargs
                if kwarg_key and kwarg_key in resolved.kwargs:
                    return reverse_lazy(url_name, kwargs={kwarg_key: resolved.kwargs.get(kwarg_key)})
                else:
                    return reverse_lazy(url_name)
        except (ValueError, AttributeError, Resolver404):
            # A referer we cannot parse, or one that is not a page of ours.
            pass

    # Default fallback if the referrer couldn't be resolved or wasn't in allowed_views
    return default_url


def scrapeURL(url):
    url_switch = url.lower()
    if 'amazon' in url_switch:
        return AmazonScrape(url)
    if 'shop4fasteners' in url_switch:
        return Shop4Scrape(url)
    if 'rs-online' in url_switch:
        return RSScrape(url)
    return None


class PartEditorCreateView(LoginRequiredMixin, RedirectView):
    """ Used to create new parts. Attempts to scrape the URL parameter
    or uses it as a part `reference` for a new part if not a URL.
    If it is blank, a new part ID is created.

    Creates records, so POST only (GET returns 405).
    """
    login_url = '/accounts/login/'
    http_method_names = ['post']

    def get_redirect_url(self, *args, **kwargs):

        def _redirect(part):
            return reverse_lazy('bom:part_editor_update', kwargs={'pk': part.id})

        team_id = self.request.POST.get('team')
        if not team_id:
            team = self.request.user.team_set.first()
        else:
            team = get_object_or_404(Team, pk=team_id)
            if not team.can_access(self.request.user):
                raise PermissionDenied("You don't have access to this team")

        # Get URL/reference parameter
        url = self.request.POST.get('url') or self.request.POST.get('reference')

        # Validate that the URL parameter is not empty
        if not url:
            # Use the helper function to set error message and determine redirect URL
            return redirect_back_with_message(
                request=self.request,
                message="Part reference is required.",
                message_key='part_error_message',
                default_url=reverse_lazy('bom:part_editor')
            )

        # If the URL parameter is NOT A URL then create a brand new part with that ID as a reference.
        term = url.lower()
        if not term.startswith('http'):

            # First check to see if this part already exits. If so, return it.
            desired_reference = term.upper()
            try:
                part = Part.objects.get(reference=desired_reference, team=team)
                return _redirect(part)
            except Part.DoesNotExist:
                # Create a new part with validation
                try:
                    # Initialize the part with both reference and name
                    part = Part(reference=desired_reference, name=desired_reference, team=team)
                    part.full_clean()
                    part.save()
                    PartSource.objects.create(part=part)
                    return _redirect(part)
                except ValidationError as e:
                    # Set error message in session and redirect back to referring page
                    error_message_dict = e.message_dict

                    if 'reference' in error_message_dict:
                        error_msg = "Part reference is required."
                    else:
                        error_msg = "Unable to create part. Please check all required fields."

                    # Use the helper function to set error message and determine redirect URL
                    return redirect_back_with_message(
                        request=self.request,
                        message=error_msg,
                        message_key='part_error_message',
                        default_url=reverse_lazy('bom:part_editor')
                    )

        # Otherwise we have a URL!  Let's try and scrape information from the page.
        scrape = scrapeURL(url)

        # No scraper knows this site: hand back a blank part (keeping the URL the
        # user pasted) for them to fill in.
        if not scrape:
            part = Part.objects.create(spec=url, team=team)
            PartSource.objects.create(part=part, url=url)
            return _redirect(part)

        def _safe(prop, default):
            try:
                return getattr(scrape, prop)()
            except Exception:
                return default

        def _download(url):
            if not url:
                return None

            # Handle base64 URLs
            if url.startswith('data:image'):
                image_data = re.sub('^data:image/.+;base64,', '', url)
                image_data = base64.b64decode(image_data)
                with io.BytesIO(image_data) as raw:
                    with Image.open(raw) as image:
                        with io.BytesIO() as output:
                            image.save(output, format='png')
                            return ContentFile(output.getvalue())

            # Handle normal image URLs.
            else:
                response = requests.get(url)
                with io.BytesIO(response.content) as raw:
                    with Image.open(raw) as image:
                        with io.BytesIO() as output:
                            image.save(output, format='png')
                            return ContentFile(output.getvalue())

        # If the URL matches an existing URL, then
        # we have a duplicate.
        match = PartSource.objects.filter(url__iexact=scrape.clean_url()).first()
        if match:
            return _redirect(match.part)

        # Create part.
        part = Part.objects.create(
            reference=_safe('reference', 0),
            name=_safe('name', ''),
            kgs=_safe('kgs', 0),
            dimensions=_safe('dimensions', ''),
            colour=_safe('colour', ''),
            # Scrapers that do not know the nature return '' - that is not a valid choice.
            nature=_safe('nature', '') or Part.NATURE_STANDARD,
            spec=_safe('spec', ''),
            team=team
        )

        # Create part source.
        PartSource.objects.create(
            part=part,
            partcode=_safe('partcode', ''),
            url=_safe('manufacturer_url', ''),
            rrp=_safe('manufacturer_rrp', 0),
            shipping=_safe('manufacturer_shipping', 0),
            minimum_order=_safe('manufacturer_minimum_order', 1),
            lead_time=_safe('manufacturer_lead_time', 1),
        )

        # Try to download and convert image to png.
        try:
            content = _download(_safe('picture', ''))
            if content:
                filename = f'{uuid.uuid4().hex}.png'
                part.picture.save(filename, content)
                part.save()
        except Exception as err:
            # todo: do something useful here
            print('Unable to convert and download image for part', err)
            raise err

        return _redirect(part)


@login_required(login_url='/accounts/login/')
def PartEditorUpdateView(request, pk):
    """ Process the form on the part editor page. Saves updates to parts and related part sources.
    """
    part = get_object_or_404(Part, pk=pk)

    # Check if user has access to this part's team
    if hasattr(part, 'team') and not part.team.can_access(request.user):
        raise PermissionDenied("You don't have access to this part")
    if request.method == 'POST':
        form = PartCreationForm(request.POST, request.FILES, instance=part)
        ps_formset = PartSourceFormset(request.POST, request.FILES, instance=part)
        d_formset = DealFormset(request.POST, request.FILES, instance=part)

        if all(f.is_valid() for f in [form, ps_formset, d_formset]):
            form.save()
            ps_formset.save()
            d_formset.save()
            url = reverse_lazy('bom:part_editor_update', kwargs={'pk': pk})
            return HttpResponseRedirect(url)

    # process form data
    else:
        form = PartCreationForm(instance=part)
        ps_formset = PartSourceFormset(instance=part)
        d_formset = DealFormset(instance=part)
        for f in d_formset.forms:
            f.fields['deal'].queryset = Deal.all_available_to_user(request.user)

    pcbpart = part.pcbpart if hasattr(part, 'pcbpart') else None
    context = {
        'form': form,
        'ps_formset': ps_formset,
        'd_formset': d_formset,
        'part': part,
        'pcbpart': pcbpart,
        'parts': Part.all_available_to_user(request.user)
    }

    # Check for error message in session and add to context
    if 'part_error_message' in request.session:
        context['part_error_message'] = request.session.pop('part_error_message')

    return render(request, os.path.join('pages', 'part_editor.html'), context)


class PartStartView(LoginRequiredMixin, View):
    """ When you go to the part editor without a part - show the first one.

    This is a plain navigation link, so it must not change anything: if the user
    has no parts yet they get a page with just the "New Part" form on it rather
    than a placeholder part being created for them.
    """
    login_url = '/accounts/login/'

    def get(self, request, *args, **kwargs):
        first = Part.all_available_to_user(request.user).first()
        if first:
            return redirect(reverse_lazy('bom:part_editor_update', kwargs={'pk': first.id}))

        # If user doesn't belong to any team, redirect to teams page
        if not request.user.team_set.exists():
            return redirect(reverse_lazy('bom:teams'))

        context = {}
        if 'part_error_message' in request.session:
            context['part_error_message'] = request.session.pop('part_error_message')
        return render(request, 'pages/part_editor_empty.html', context)


class PartDuplicateView(LoginRequiredMixin, View):
    """ Duplicate a given part. POST only. """
    login_url = '/accounts/login/'

    def post(self, request, *args, **kwargs):

        # Determine the part to be duplicated.
        source_id = request.POST.get('source_id')
        if not source_id:
            return HttpResponseBadRequest('source_id was not specified - cannot duplicate part')
        part = get_object_or_404(Part, id=source_id)

        # Check if user has access to this part's team
        if not part.can_access(request.user):
            raise PermissionDenied("You don't have access to this part")

        # Determine the name of the new part reference.
        target_reference = request.POST.get('target_reference')
        if not target_reference:
            target_reference = 'COPY'  # TODO: Consider UUID here

        # Duplicate it. Set the primary key to None to regenerate it as a new object.
        picture_path = part.picture.path if part.picture else None
        old_id = part.pk

        part.pk = None
        part.picture = None
        part.reference = f'{part.reference}-{target_reference}'
        part.save()

        if picture_path and os.path.exists(picture_path):
            with open(picture_path, 'rb') as fh:
                with ContentFile(fh.read()) as file_content:
                    part.picture.save('temp.png', file_content)  # temp.png will be renamed automatically

        # Copy the part sources.
        for source in PartSource.objects.filter(part=old_id):
            source.partcode = f'{source.partcode}-COPY'  # TODO FIXME: Is this correct behaviour?
            source.pk = None
            source.part = part
            source.save()

        return redirect(reverse_lazy('bom:part_editor_update', kwargs={'pk': part.id}))


class MainPageTester(TemplateView):
    """ For testing out the template page. """
    template_name = 'partial/app.html'


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


class DashboardView(LoginRequiredMixin, TemplateView):
    """ Index view, after a successful login, show all top level assemblies """
    login_url = '/accounts/login/'
    template_name = 'pages/dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        # Ensure user is a member of a team before getting to the dashboard
        # However, allow superusers to access the dashboard even without teams
        if (not request.user.is_anonymous
                and request.user.team_set.count() == 0
                and not request.user.is_superuser):
            return redirect(reverse_lazy('bom:teams'))
        return super(DashboardView, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(DashboardView, self).get_context_data(**kwargs)
        teams = self.request.user.team_set.values_list('id')

        # Use annotate to create a custom field based on the deprecation date.
        products = SubAssembly.objects.filter(team__in=teams, is_toplevel=True).annotate(
            is_deprecated=Case(
                When(deprecated__lte=datetime.date.today(), then=True),
                default=False,
                output_field=BooleanField()
            )
        ).order_by('is_deprecated', 'reference')
        context['products'] = products

        # Check for error messages in session and add to context
        if 'error_message' in self.request.session:
            context['error_message'] = self.request.session.pop('error_message')

        # Also check for part-specific error messages
        if 'part_error_message' in self.request.session:
            context['error_message'] = self.request.session.pop('part_error_message')

        return context


class TeamsView(LoginRequiredMixin, TemplateView):
    """Teams view"""

    login_url = "/accounts/login/"
    template_name = "pages/teams.html"

    def get_context_data(self, **kwargs):
        context = super(TeamsView, self).get_context_data(**kwargs)

        # Check for messages in session and add to context
        for key in ("error_message", "success_message", "invite_link"):
            if key in self.request.session:
                context[key] = self.request.session.pop(key)

        return context


class UserSettingsView(LoginRequiredMixin, TemplateView):
    """ Per-user settings: account details and a summary of the user's privileges. """

    login_url = '/accounts/login/'
    template_name = 'pages/user_settings.html'

    def get_context_data(self, **kwargs):
        context = super(UserSettingsView, self).get_context_data(**kwargs)
        context.setdefault('form', UserAccountForm(instance=self.request.user))
        context['teams'] = self.request.user.team_set.select_related('owner').order_by('name')
        context['success_message'] = self.request.session.pop('settings_success_message', None)
        return context

    def post(self, request, *args, **kwargs):
        form = UserAccountForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            request.session['settings_success_message'] = 'Account details saved.'
            return HttpResponseRedirect(reverse_lazy('bom:user_settings'))
        return self.render_to_response(self.get_context_data(form=form))


class ToolProductionPhases(LoginRequiredMixin, TemplateView):
    """ Production phases view to show what assemblies are allocated to what phases. """
    template_name = 'pages/tool_production_phases.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        # Sort assemblies by production phase
        product_id = self.kwargs.get('pk')
        root = get_object_or_404(SubAssembly, id=product_id)

        # Check team access
        if not root.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        assemblies = root.children.all().order_by('production_phase')
        phases = defaultdict(list)
        for assy in assemblies:
            phases[assy.production_phase].append(assy)

        # Count the uses.
        counted_parts = Counter()
        counted_assemblies = Counter()
        root.collect_and_count_parts(counted_parts, counted_assemblies)

        # Add to the context.
        context = super(ToolProductionPhases, self).get_context_data(**kwargs)
        context['phases'] = dict(phases)
        context['assemblies'] = assemblies
        context['counted_assemblies'] = counted_assemblies
        return context


class ToolOrphanFinder(LoginRequiredMixin, TemplateView):
    """ Find orphan assemblies and parts. """
    template_name = 'pages/tool_orphan_finder.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        # Find orphans.
        project = get_object_or_404(SubAssembly, id=self.kwargs.get('pk'))

        # Check team access
        if not project.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        orphan_parts = [p for p in Part.all_available_to_user(self.request.user) if p.is_orphan]
        orphan_assemblies = [a for a in project.children.all() if a.is_orphan]

        # Add to the context.
        context = super(ToolOrphanFinder, self).get_context_data(**kwargs)
        context['orphan_parts'] = orphan_parts
        context['orphan_assemblies'] = orphan_assemblies
        return context


class ToolSalesCodes(LoginRequiredMixin, TemplateView):
    """ Show all parts and subassemblies with sales codes """

    template_name = 'pages/tool_sales_codes.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        # Get all the items with sales codes to display
        project = get_object_or_404(SubAssembly, id=self.kwargs.get('pk'))

        # Check team access
        if not project.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        parts = [p for p in Part.all_available_to_user(self.request.user) if p.sale_code]
        assemblies = [a for a in project.children.all() if a.sale_code]
        # Filter further and fetch ones with sales codes but no HS codes
        # since we can't filter in the template
        parts_without_hs = [p for p in parts if not p.hs_code]
        assemblies_without_hs = [a for a in assemblies if not a.hs_code]

        # Add to the context.
        context = super(ToolSalesCodes, self).get_context_data(**kwargs)
        context['parts'] = parts
        context['assemblies'] = assemblies
        context['parts_without_hs'] = parts_without_hs
        context['assemblies_without_hs'] = assemblies_without_hs
        return context


class ToolDeals(LoginRequiredMixin, TemplateView):
    """ View for a page that displays all `Deals` for a `Project` so that they can be edited. """
    template_name = 'pages/tool_deals.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        # Sort assemblies by production phase
        product_id = self.kwargs.get('pk')
        root = get_object_or_404(SubAssembly, id=product_id)

        # Check team access
        if not root.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        team = root.team

        dealparts = {}
        deals = {}
        for deal in team.deals.all():
            d_formset = DealPartFormset(instance=deal)
            for f in d_formset.forms:
                f.fields['part'].queryset = Part.all_available_to_user(self.request.user)
            dealparts[deal] = d_formset
            deals[deal] = DealForm(instance=deal)
            deals[deal]['team'].queryset = self.request.user.team_set.all()

        # Add to the context.
        context = super(ToolDeals, self).get_context_data(**kwargs)
        context['dealparts'] = dealparts
        context['deals'] = deals
        context['new_dform'] = DealForm()
        context['pk'] = product_id
        context['product'] = root
        return context


class ToolDealLineItemUpdateView(LoginRequiredMixin, RedirectView):

    def post(self, request, *args, **kwargs):
        deal_id = self.kwargs.get('deal_id')
        deal = get_object_or_404(Deal, pk=deal_id)

        # Check if user has access to this deal's team
        if not deal.team.can_access(request.user):
            raise PermissionDenied("You don't have access to this deal")

        formset = DealPartFormset(self.request.POST, instance=deal)
        if formset.is_valid():
            formset.save()
        return redirect(self.get_redirect_url())

    def get_redirect_url(self, *args, **kwargs):
        pk = self.kwargs.get('pk')
        return reverse_lazy('bom:tools_deals', kwargs={'pk': pk})


class ToolDealUpdateView(LoginRequiredMixin, RedirectView):

    def post(self, request, *args, **kwargs):
        deal_id = self.kwargs.get('deal_id')
        deal = get_object_or_404(Deal, pk=deal_id)

        # Check if user has access to this deal's team
        if not deal.team.can_access(request.user):
            raise PermissionDenied("You don't have access to this deal")

        form = DealForm(self.request.POST, instance=deal)
        if form.is_valid():
            form.save()
        return redirect(self.get_redirect_url())

    def get_redirect_url(self, *args, **kwargs):
        pk = self.kwargs.get('pk')
        return reverse_lazy('bom:tools_deals', kwargs={'pk': pk})


class ToolDealCreateView(LoginRequiredMixin, RedirectView):

    def post(self, request, *args, **kwargs):
        form = DealForm(self.request.POST)
        if form.is_valid():
            # A deal belongs to a team, so only members of that team may create one for it.
            if not form.cleaned_data['team'].can_access(request.user):
                raise PermissionDenied("You don't have access to this team")
            form.save()
        return redirect(self.get_redirect_url())

    def get_redirect_url(self, *args, **kwargs):
        pk = self.kwargs.get('pk')
        return reverse_lazy('bom:tools_deals', kwargs={'pk': pk})


@login_required(login_url='/accounts/login/')
def export_purchasing(request, pk=None):
    """ Export a Purchasing Spreadsheet as an Excel file.
    """

    project = get_object_or_404(SubAssembly, id=pk)

    # Add team access check
    if not project.can_access(request.user):
        raise PermissionDenied("You don't have access to this project")

    # Open the excel file.
    with io.BytesIO() as output:
        workbook = export_purchasing_spreadsheet(project, output, request.user)
        workbook.close()
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        download_name = '%s-%s' % (project.name, datetime.datetime.now().strftime('Purchasing-%Y%V'))
        response['Content-Disposition'] = (f'attachment;filename={download_name}.xlsx')
        return response


@login_required(login_url='/accounts/login/')
def export_bom_as_xlsx(request, pk=None):
    """ Export the BOM summary as an Excel file.
    """

    project = get_object_or_404(SubAssembly, id=pk)

    # Add team access check
    if not project.can_access(request.user):
        raise PermissionDenied("You don't have access to this project")

    # Open the excel file.
    with io.BytesIO() as output:
        workbook = export_database_to_excel(project, output)
        workbook.close()
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        download_name = '%s-%s' % (project.name, datetime.datetime.now().strftime('BOM-%Y%V'))
        response['Content-Disposition'] = (f'attachment;filename={download_name}.xlsx')
        return response


@login_required(login_url='/accounts/login/')
@user_passes_test(is_superuser)
def export_backup(request):
    """ Export a zipfile backup of the database and image content.
    """
    out = StringIO()
    management.call_command('dumpdata', format='json', exclude=['contenttypes'], stdout=out)

    with io.BytesIO() as output:
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipcontent:
            # Add the database.
            # TODO: Swap for `DATABASES[default][NAME]`
            zipcontent.writestr('database.json', out.getvalue())

            # Add the asset files.
            for root, dirs, files in os.walk(settings.MEDIA_ROOT):
                for filename in files:
                    zipcontent.write(os.path.join(root, filename))
        out.close()

        # Return the response.
        response = HttpResponse(output.getvalue(), content_type='application/zip')
        download_name = datetime.datetime.now().strftime('bomnado-%Y%V--%Y-%m-%d-%H-%M-%S')
        response['Content-Disposition'] = (f'attachment;filename={download_name}.zip')
        return response


@login_required(login_url='/accounts/login/')
@require_POST
def attachment_delete(request, attachment_pk):
    """ Delete an `Attachment` that has been previously attached to a model.

    This will locate the attachment, validate that it exists, and remove from
    the disk. POST only.
    """
    attachment = get_object_or_404(Attachment, pk=attachment_pk)

    # Check if user has access to the related object's team
    content_object = attachment.content_object
    if hasattr(content_object, 'can_access'):
        if not content_object.can_access(request.user):
            raise PermissionDenied("You don't have access to this resource")
    elif hasattr(content_object, 'team'):
        if not content_object.team.can_access(request.user):
            raise PermissionDenied("You don't have access to this resource")

    path = attachment.attachment_file.path

    # TODO: Disallow deleting attachments already in use in markdown fields.

    # Delete the file from the disk.
    # NOTE: Exception is allowed here as it will pass OSError back up to the frontend
    # and stop execution removing the attachment from the DB.
    if os.path.exists(path):
        os.remove(path)

    # Remove from the DB.
    attachment.delete()

    return HttpResponse(status=200)


@login_required(login_url='/accounts/login/')
def attachment_attach(request, model_name, model_pk):
    """ Attach a file to a specified Django model instance.

    The name of the model (e.g. `Part`) and it's primary key need to be specified.
    This will upload the file to the server and return a customised dictionary
    with useful information in (file name, i.e. if renamed) that the UI can use.
    """
    app_name = request.resolver_match.app_name  # bom
    model = apps.get_model(app_name, model_name)
    obj = get_object_or_404(model, pk=model_pk)

    # Check team access based on model type
    if hasattr(obj, 'can_access') and callable(getattr(obj, 'can_access')):
        if not obj.can_access(request.user):
            raise PermissionDenied("You don't have access to this resource")
    elif hasattr(obj, 'team'):
        if not obj.team.can_access(request.user):
            raise PermissionDenied("You don't have access to this resource")

    form = AttachmentForm(request.POST, request.FILES)

    # You can't go attachin' without files now.
    if request.method != 'POST':
        return HttpResponseNotAllowed()

    # Check we have all the fields we need.
    if not form.is_valid():
        return JsonResponse(form.errors, status=400)

    # Save to the DB
    form.save(request, obj)

    # Prep a response describing the new attachment.
    attachment = form.instance
    response_data = {
        'url': attachment.attachment_file.url,
        'filename': attachment.filename,
        'created': attachment.created,
        'delete_link': attachment.delete_link
    }
    return JsonResponse(response_data)


class NewTeamView(LoginRequiredMixin, RedirectView):
    login_url = "/accounts/login/"

    def get_redirect_url(self, *args, **kwargs):
        # Get the team name from POST data
        team_name = self.request.POST.get("name", "").strip()

        # Validate that team name is provided
        if not team_name:
            return redirect_back_with_message(
                request=self.request,
                message="Team name is required.",
                message_key="error_message",
                default_url=reverse_lazy("bom:teams"),
            )

        # Check if a team with this name already exists
        if Team.objects.filter(name__iexact=team_name).exists():
            return redirect_back_with_message(
                request=self.request,
                message=f"A team with the name '{team_name}' already exists.",
                message_key="error_message",
                default_url=reverse_lazy("bom:teams"),
            )

        # Create the team if validation passes
        try:
            # Create instance first without saving to database, set owner to current user
            t = Team(name=team_name, owner=self.request.user)
            # Validate before saving
            t.full_clean()
            # Save only after validation passes
            t.save()
            t.users.add(self.request.user)
        except ValidationError as e:
            error_message_dict = getattr(e, "message_dict", {})

            # Handle validation errors
            if "name" in error_message_dict:
                error_msg = error_message_dict["name"][0]
            else:
                error_msg = "Team validation failed: " + ", ".join(
                    [f"{k}: {v[0]}" for k, v in error_message_dict.items()]
                )

            return redirect_back_with_message(
                request=self.request,
                message=error_msg,
                message_key="error_message",
                default_url=reverse_lazy("bom:teams"),
            )

        return reverse_lazy("bom:teams")


def make_set_password_link(request, user):
    """ An absolute URL that lets `user` choose a password, using Django's password-reset machinery.

    Valid for `settings.PASSWORD_RESET_TIMEOUT` and only until it is used.
    """
    return request.build_absolute_uri(reverse('password_reset_confirm', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
    }))


class AddToTeamView(LoginRequiredMixin, RedirectView):
    """ Add a user to a team (owner only).

    The owner enters a username or email address. An existing account is added
    straight away. An unknown *email address* creates a new account for that
    person, adds it to the team, and gives the owner a "set your password" link
    to pass on - so new users can be onboarded even when outgoing email is not
    configured. The same link is also emailed, best-effort.
    """
    login_url = '/accounts/login/'

    @team_owner_required
    def get_redirect_url(self, *args, **kwargs):
        request = self.request
        team = request.user.team_set.get(id=kwargs.get('pk'))
        identifier = (request.POST.get('username') or '').strip()
        teams_url = reverse_lazy('bom:teams')

        def _error(message):
            return redirect_back_with_message(request=request, message=message, default_url=teams_url)

        if not identifier:
            return _error('Enter a username or email address to add to the team.')

        # Existing account, by username or email (either way, case-insensitive).
        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)).order_by('pk').first()
        if user:
            if team.users.filter(pk=user.pk).exists():
                return _error(f'{user.email or user.username} is already a member of {team.name}.')
            team.users.add(user)
            request.session['success_message'] = f'{user.email or user.username} has been added to {team.name}.'
            return teams_url

        # Nobody by that name. Only an email address can be used to invite someone new.
        try:
            validate_email(identifier)
        except ValidationError:
            return _error(f'No user called "{identifier}" was found. '
                          'Enter an email address to invite someone new.')

        user = User(username=username_from_email(identifier), email=identifier)
        user.set_unusable_password()
        try:
            user.full_clean()
        except ValidationError as e:
            return _error('Could not create that user: ' + '; '.join(
                f'{field}: {errors[0]}' for field, errors in e.message_dict.items()))
        user.save()
        team.users.add(user)

        link = make_set_password_link(request, user)
        try:
            send_mail(
                subject=f'You have been added to {team.name} on Bomnado',
                message=(f'{request.user.email or request.user.username} has added you to the team '
                         f'"{team.name}" on Bomnado.\n\n'
                         f'Choose a password to get started:\n\n{link}\n'),
                from_email=None,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            # Email is optional here - the owner is shown the link regardless.
            pass

        request.session['success_message'] = (
            f'Created an account for {user.email} and added it to {team.name}. '
            'Send them the link below so they can choose a password (it can only be used once).')
        request.session['invite_link'] = link
        return teams_url


class RemoveFromTeamView(LoginRequiredMixin, RedirectView):
    login_url = '/accounts/login/'

    @team_owner_required
    def get_redirect_url(self, *args, **kwargs):
        request = self.request
        username = request.POST.get('username')
        t = request.user.team_set.get(id=kwargs.get('pk'))
        users = User.objects.filter(username=username)
        if users:
            t.users.remove(users.first())
            t.save()
        return reverse_lazy('bom:teams')
