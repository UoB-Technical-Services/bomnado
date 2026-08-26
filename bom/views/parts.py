""" The part editor: creating (from a reference or a pasted link), editing, duplicating. """
import os

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.http import HttpResponseRedirect, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic.base import RedirectView

from bom.forms import PartCreationForm, PartSourceFormset, DealFormset, NamedPieceFormset
from bom.models import Part, PartSource, NamedPiece, Team, Deal
from bom.views.shared import redirect_back_with_message


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
        url = (self.request.POST.get('url') or self.request.POST.get('reference') or '').strip()

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

        # A URL: the part starts with it as its first supplier row. The part page's AI helpers
        # ("Fill in from the suppliers' pages") read the page and fill the rest in.
        match = PartSource.objects.filter(url__iexact=url, part__team=team).first()
        if match:
            return _redirect(match.part)
        part = Part.objects.create(team=team)
        PartSource.objects.create(part=part, url=url)
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
        piece_formset = NamedPieceFormset(request.POST, request.FILES, instance=part)

        if all(f.is_valid() for f in [form, ps_formset, d_formset, piece_formset]):
            form.save()
            ps_formset.save()
            d_formset.save()
            piece_formset.save()
            url = reverse_lazy('bom:part_editor_update', kwargs={'pk': pk})
            return HttpResponseRedirect(url)

    # process form data
    else:
        form = PartCreationForm(instance=part)
        ps_formset = PartSourceFormset(instance=part)
        d_formset = DealFormset(instance=part)
        piece_formset = NamedPieceFormset(instance=part)
        for f in d_formset.forms:
            f.fields['deal'].queryset = Deal.all_available_to_user(request.user)

    # Show the suffix inputs as `PARENT.` + suffix. The empty form is built once here
    # (each access to `empty_form` makes a new one) so the template can clone it.
    piece_empty_form = piece_formset.empty_form
    for f in [*piece_formset.forms, piece_empty_form]:
        f.fields['suffix'].widget.custom['prepend'] = f'{part.reference}{NamedPiece.SEPARATOR}'

    pcbpart = part.pcbpart if hasattr(part, 'pcbpart') else None
    context = {
        'form': form,
        'ps_formset': ps_formset,
        'd_formset': d_formset,
        'piece_formset': piece_formset,
        'piece_empty_form': piece_empty_form,
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

        # Copy the pieces (the new part gets its own `PARENT>SUFFIX` references).
        for piece in NamedPiece.objects.filter(part=old_id):
            piece_picture_path = piece.picture.path if piece.picture else None
            piece.pk = None
            piece.part = part
            piece.picture = None
            piece.save()
            if piece_picture_path and os.path.exists(piece_picture_path):
                with open(piece_picture_path, 'rb') as fh:
                    with ContentFile(fh.read()) as file_content:
                        piece.picture.save(os.path.basename(piece_picture_path), file_content)

        return redirect(reverse_lazy('bom:part_editor_update', kwargs={'pk': part.id}))
