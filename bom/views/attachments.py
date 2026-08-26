""" Attaching files to records and removing them. """
import os

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from bom.forms import AttachmentForm
from bom.models import Attachment


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
