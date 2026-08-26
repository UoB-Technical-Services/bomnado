""" The AI assistant: the chat drawer's endpoints and the activity page. """

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy
from django.utils.html import escape
from django.views.decorators.http import require_POST
from django.views.generic.base import TemplateView

from bom.models import Part, SubAssembly, Attachment, AIJob, AIThread, AIMessage
from bom.ai import chat as ai_chat_module
from bom.ai import client as ai_client
from bom.ai import jobs as ai_jobs


@login_required(login_url='/accounts/login/')
@require_POST
def ai_test_connection(request):
    """ "Test connection" on the settings page: a one-line verdict, swapped in by htmx. """
    try:
        name = ai_client.test_connection(request.user)
    except ai_client.AINotConfigured as error:
        return HttpResponse(f'<span class="text-danger">{escape(error)}</span>')
    except Exception as error:  # the SDK's typed errors all carry a readable message
        return HttpResponse(f'<span class="text-danger">Could not connect: {escape(str(error)[:200])}</span>')
    return HttpResponse(f'<span class="text-success">Connected - {escape(name)} is ready.</span>')


# ---------------------------------------------------------------------------------------------
# AI assistant: the chat window (see `bom.ai.chat`), its turns (`bom.ai.jobs`) and the naming guide.

def _thread(request, thread_id):
    thread = get_object_or_404(AIThread, pk=thread_id)
    if not thread.can_access(request.user):
        raise PermissionDenied("You don't have access to this conversation")
    return thread


def chat_context(request):
    """ The record the window was opened over - `context=part:12` - as `{"kind", "id"}`, if it is real
    and theirs; else `{}`. """
    text = (request.POST.get('context') or request.GET.get('context') or '').strip()
    kind, _, pk = text.partition(':')
    model = {'part': Part, 'assembly': SubAssembly}.get(kind)
    record = model.objects.filter(pk=pk).first() if model and pk.isdigit() else None
    if record is None or not record.can_access(request.user):
        return {}
    return {'kind': kind, 'id': record.pk, 'reference': record.reference}


def render_thread(request, thread, error='', messages_only=False):
    """ The window's body for a thread: its messages, the running turn (polled), the composer. The
    messages poll themselves while a turn runs and swap only themselves (`messages_only`). """
    job = thread.latest_job if thread is not None else None
    if job is not None:
        job.reap_if_stale()
    page = chat_context(request)
    context = {'thread': thread, 'job': job, 'error': error, 'ai_ready': _ai_ready(request.user), 'page': page,
               'messages': list(thread.messages.select_related('job')) if thread is not None else [],
               'touched': (job.outcome or {}).get('touched', []) if job is not None and job.is_finished else [],
               'suggestions': _suggestions(page)}
    return render(request, 'partial/ai_chat_messages.html' if messages_only else 'partial/ai_chat_thread.html', context)


def _suggestions(context):
    """ Jumping-off points for an empty conversation, for the page it was opened over. """
    reference = context.get('reference', '')
    if context.get('kind') == 'part':
        return [
            {'label': 'Find other suppliers', 'send': True,
             'prompt': f'Find other suppliers for `{reference}` and add the good ones, with unit prices ex VAT.'},
            {'label': "Fill in from the suppliers' pages", 'send': True,
             'prompt': f'Fill in `{reference}` from its supplier pages and attachments: spec, dimensions, weight, colour, '
                       'manufacturer, part numbers and prices. Keep anything already filled in.'},
            {'label': 'Draft QC steps', 'send': True,
             'prompt': f'Draft quality-control steps for `{reference}` and set them on the part as a task list.'},
        ]
    if context.get('kind') == 'assembly':
        return [
            {'label': 'Check this BOM for gaps', 'send': True,
             'prompt': f'Check the bill of materials of `{reference}`: anything missing, parts without a supplier or '
                       'price, quantities that look wrong, deprecated parts. Report; fix only what is obvious.'},
            {'label': 'Draft instructions', 'send': True,
             'prompt': f'Draft assembly instructions for `{reference}` from its line items and set them on the assembly.'},
        ]
    return [
        {'label': 'Create a part from a link', 'send': False, 'prompt': 'Create a part from this link: '},
        {'label': 'Turn files into parts', 'send': False,
         'prompt': 'Turn the attached files into parts. Search for existing parts first, follow the naming guide, and '
                   'attach each file to the part it documents.'},
        {'label': 'What needs reviewing?', 'send': True,
         'prompt': 'Which parts and assemblies have open "requires human review" comments? List them with what changed.'},
    ]


def _ai_ready(user):
    try:
        ai_jobs.check_can_use(user)
    except ai_client.AINotConfigured:
        return False
    return True


@login_required(login_url='/accounts/login/')
def ai_chat(request):
    """ The window opening: `?thread=<id>` for a particular conversation, else the latest one (a fresh
    window when there is none). """
    thread = None
    if request.GET.get('thread', '').isdigit():
        thread = AIThread.objects.filter(pk=int(request.GET['thread']), user=request.user).first()
    if thread is None and request.GET.get('thread') != 'new':
        thread = AIThread.objects.filter(user=request.user).first()
    return render_thread(request, thread)


@login_required(login_url='/accounts/login/')
@require_POST
def ai_chat_send(request):
    """ A message from the person: stored on the thread (a new one if there is none), with any files
    as attachments, then answered by a job. Returns the thread, polling. """
    thread = None
    if request.POST.get('thread', '').isdigit():
        thread = AIThread.objects.filter(pk=int(request.POST['thread']), user=request.user).first()
    text = (request.POST.get('text') or '').strip()[:20000]
    files = request.FILES.getlist('files')[:20]
    if not text and not files:
        return render_thread(request, thread, error='Say something, or drop a file in.')
    try:
        ai_jobs.check_can_use(request.user)
    except ai_client.AINotConfigured as why:
        return render_thread(request, thread, error=str(why))
    context = chat_context(request)
    if thread is None:
        team = request.user.team_set.first()
        if context:
            record = (Part if context['kind'] == 'part' else SubAssembly).objects.get(pk=context['id'])
            team = record.team
        thread = AIThread.objects.create(user=request.user, team=team, context=context)
    elif context != thread.context:
        thread.context = context  # "this" now means the page they are on - or nothing, off a record's page
        thread.save(update_fields=['context'])
    job = thread.latest_job
    if job is not None and job.reap_if_stale().is_running:
        return render_thread(request, thread, error='Wait for the current answer, or stop it.')

    blocks = [ai_chat_module.context_placeholder(context)]
    for upload in files:
        attachment = Attachment(content_object=thread)
        attachment.attachment_file.save(upload.name, upload)
        blocks.append(ai_chat_module.file_placeholder(attachment))
    blocks.append({'type': 'text', 'text': text or 'I have added these files.'})
    AIMessage.objects.create(thread=thread, role='user', content=blocks)
    try:
        ai_jobs.start(thread)
    except ai_client.AINotConfigured as why:
        return render_thread(request, thread, error=str(why))
    return render_thread(request, thread)


@login_required(login_url='/accounts/login/')
def ai_chat_status(request, thread_id):
    """ The messages, polled by the window while a turn runs. """
    return render_thread(request, _thread(request, thread_id), messages_only=True)


@login_required(login_url='/accounts/login/')
@require_POST
def ai_chat_stop(request, thread_id):
    thread = _thread(request, thread_id)
    job = thread.latest_job
    if job is not None:
        ai_jobs.cancel(job)
    return render_thread(request, thread, messages_only=True)


@login_required(login_url='/accounts/login/')
@require_POST
def ai_chat_retry(request, thread_id):
    """ Answer the last message again: the failed turn's messages go, a new job starts. """
    thread = _thread(request, thread_id)
    job = thread.latest_job
    if job is not None and job.reap_if_stale().is_running:
        return render_thread(request, thread, error='It is still running.', messages_only=True)
    if job is not None and job.status == AIJob.STATUS_FAILED:
        thread.messages.filter(job=job).delete()
    try:
        ai_jobs.start(thread)
    except ai_client.AINotConfigured as why:
        return render_thread(request, thread, error=str(why), messages_only=True)
    return render_thread(request, thread, messages_only=True)


@login_required(login_url='/accounts/login/')
@require_POST
def ai_chat_delete(request, thread_id):
    """ Delete a conversation: the thread and its messages go; its job rows stay for the month's
    spend but leave the activity list. From the activity page (a plain form) it returns there. """
    thread = AIThread.objects.filter(pk=thread_id).first()
    if thread is not None:
        if not thread.can_access(request.user):
            raise PermissionDenied("You don't have access to this conversation")
        if thread.latest_job is not None:
            ai_jobs.cancel(thread.latest_job)
    # A conversation deleted before its rows were cleared leaves rows pointing at nothing: clearing
    # by the id works whether the thread still exists or not.
    AIJob.objects.filter(user=request.user, object_id=thread_id,
                         content_type=ContentType.objects.get_for_model(AIThread)).update(cleared=True)
    if thread is not None:
        thread.delete()
    if request.headers.get('HX-Request'):
        return render_thread(request, None)
    return HttpResponseRedirect(reverse_lazy('bom:ai_jobs'))


@login_required(login_url='/accounts/login/')
@require_POST
def ai_job_cancel(request, job_id):
    """ Stop, from the activity page. """
    job = get_object_or_404(AIJob, pk=job_id)
    if not job.can_access(request.user):
        raise PermissionDenied("You don't have access to this job")
    ai_jobs.cancel(job)
    return HttpResponseRedirect(reverse_lazy('bom:ai_jobs'))


class AIJobsView(LoginRequiredMixin, TemplateView):
    """ What the AI is doing for this user, and has done: running turns with Stop, then recent ones. """
    login_url = '/accounts/login/'
    template_name = 'pages/ai_jobs.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        jobs = [job.reap_if_stale() for job in AIJob.objects.filter(user=self.request.user, cleared=False)[:50]]
        context['running'] = [job for job in jobs if job.is_running]
        context['recent'] = [job for job in jobs if not job.is_running][:30]
        context['ai_settings'] = ai_client.settings_for(self.request.user)
        return context


@login_required(login_url='/accounts/login/')
@require_POST
def ai_job_clear(request, job_id):
    """ Take one finished row off the activity list (the month's spend is unaffected). """
    job = get_object_or_404(AIJob, pk=job_id, user=request.user)
    if job.is_finished:
        job.cleared = True
        job.save(update_fields=['cleared'])
    return HttpResponseRedirect(reverse_lazy('bom:ai_jobs'))


@login_required(login_url='/accounts/login/')
@require_POST
def ai_jobs_clear(request):
    """ Clear the activity list: finished jobs are hidden (they still count towards the month's spend). """
    AIJob.objects.filter(user=request.user, cleared=False).exclude(
        status__in=[AIJob.STATUS_QUEUED, AIJob.STATUS_RUNNING]).update(cleared=True)
    return HttpResponseRedirect(reverse_lazy('bom:ai_jobs'))
