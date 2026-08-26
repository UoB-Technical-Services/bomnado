""" The activity strip: history entries, feedback, revert. """

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect, Http404
from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from bom.models import Part, SubAssembly, Feedback
from bom.utils import activity as activity_log


# ---------------------------------------------------------------------------------------------
# Comments and activity (see `bom.utils.activity` and `partial/activity.html`).

""" The editor pages that carry an activity strip, by the `model_name` in their URLs. """
ACTIVITY_MODELS = {'part': Part, 'subassembly': SubAssembly}


def _activity_object(request, model_name, pk):
    """ The part / assembly an activity URL is about, or 404 / 403. """
    model = ACTIVITY_MODELS.get(model_name)
    if model is None:
        raise Http404(model_name)
    obj = get_object_or_404(model, pk=pk)
    if not obj.can_access(request.user):
        raise PermissionDenied("You don't have access to this record")
    return obj


def _activity_page_url(obj):
    if isinstance(obj, Part):
        return reverse_lazy('bom:part_editor_update', kwargs={'pk': obj.pk})
    return reverse_lazy('bom:assembly_editor_update', kwargs={'pk': obj.pk})


def render_activity(request, obj, offset=0, entries_only=False):
    """ The whole strip (feedback + timeline), or just one page of timeline entries. """
    template = 'partial/activity_entries.html' if entries_only else 'partial/activity.html'
    return render(request, template, activity_log.activity_context(obj, offset))


@login_required(login_url='/accounts/login/')
def activity_entries(request, model_name, pk):
    """ One page of the timeline (`?offset=N`): what "Show more" fetches. """
    obj = _activity_object(request, model_name, pk)
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except ValueError:
        offset = 0
    return render_activity(request, obj, offset, entries_only=True)


@login_required(login_url='/accounts/login/')
@require_POST
def feedback_add(request, model_name, pk):
    obj = _activity_object(request, model_name, pk)
    text = request.POST.get('text', '').strip()
    if text:
        Feedback.objects.create(content_object=obj, text=text, author=request.user)
    return render_activity(request, obj)


def _feedback(request, feedback_id):
    item = get_object_or_404(Feedback, pk=feedback_id)
    if not item.can_access(request.user):
        raise PermissionDenied("You don't have access to this record")
    return item


@login_required(login_url='/accounts/login/')
@require_POST
def feedback_resolve(request, feedback_id):
    item = _feedback(request, feedback_id)
    item.resolve(request.user)
    return render_activity(request, item.content_object)


@login_required(login_url='/accounts/login/')
@require_POST
def feedback_reopen(request, feedback_id):
    item = _feedback(request, feedback_id)
    item.reopen()
    return render_activity(request, item.content_object)


@login_required(login_url='/accounts/login/')
@require_POST
def activity_revert(request, model_name, pk, historical_model, history_id):
    """ Undo one entry of the strip, then reload the page: the form fields have changed. """
    obj = _activity_object(request, model_name, pk)
    activity_log.revert(obj, historical_model, history_id)
    return HttpResponseRedirect(f'{_activity_page_url(obj)}#activity')
