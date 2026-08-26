""" The Excel exports and the database backup. """
import datetime
import io
import os
import zipfile
from io import StringIO

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core import management
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from bom.models import SubAssembly
from bom.utils.export import is_superuser
from bom.utils.export.excel import export_database_to_excel, export_purchasing_spreadsheet
from general.utils import perform_backup


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
        workbook = export_purchasing_spreadsheet(project, output, request.user,
                                                 base_url=request.build_absolute_uri('/'))
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
        workbook = export_database_to_excel(project, output, request.user)
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
@user_passes_test(is_superuser, login_url='/accounts/login/')
@require_POST
def backup_now(request):
    """ The user menu's "Back Up Now": a database dump and a media archive into the backup
    storage (`backups/` by default), keeping the newest few of each - the same
    `general.utils.perform_backup` the nightly task runs. README.md says how to restore. """
    perform_backup()
    request.session['settings_success_message'] = ('Backed up the database and the media files to the backup '
                                                   'folder. README.md says how to restore.')
    return HttpResponseRedirect(reverse_lazy('bom:user_settings'))
