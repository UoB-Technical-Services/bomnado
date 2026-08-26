""" Running a turn of the chat as an `AIJob`: in a Celery worker, a background thread
(development: no broker, and the window polls for progress) or inline (tests).

`start` checks the person can use AI at all (a key, within budget); `run` does the work and
records the outcome - never raising, so a failure is something the window can show and
retry rather than a dead thread.
"""
import logging
import threading

import anthropic
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection

from bom.ai.chat import AIRefused, Cancelled, run_turn
from bom.ai.client import AINotConfigured, settings_for
from bom.ai.fetch import FetchError, UnsafeURL
from bom.models import AIJob

log = logging.getLogger(__name__)


def check_can_use(user):
    """ Raise `AINotConfigured` unless the user has a key and is within budget. """
    config = settings_for(user)
    if config is None or not config.is_configured:
        raise AINotConfigured('Add an AI API key under Settings to use this.')
    if config.over_budget():
        raise AINotConfigured('Your monthly AI budget is used up; raise it under Settings to continue.')


def start(thread):
    """ Answer the thread's latest message: a queued job, running. Raises `AINotConfigured`. """
    check_can_use(thread.user)
    job = AIJob(user=thread.user, team=thread.team, kind=AIJob.KIND_CHAT, content_object=thread)
    job.save()
    return queue(job)


def queue(job):
    from bom.tasks import run_ai_job
    job.status = AIJob.STATUS_QUEUED
    job.save(update_fields=['status'])
    if getattr(settings, 'BOMNADO_AI_THREADS', False):
        threading.Thread(target=_run_in_thread, args=(job.id,), daemon=True, name=f'ai-job-{job.id}').start()
    elif getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        run_ai_job.apply(args=[job.id])
        job.refresh_from_db()
    else:
        run_ai_job.delay(job.id)
    return job


def _run_in_thread(job_id):
    try:
        run(job_id)
    finally:
        connection.close()


def run(job_id):
    """ Do a queued job's work. Never raises: failures are recorded on the job. """
    job = AIJob.objects.select_related('user', 'team').get(pk=job_id)
    job.mark_running()
    try:
        outcome = run_turn(job)
        if job.cancel_wanted():
            raise Cancelled('Stopped.')
        job.outcome = outcome
        job.save(update_fields=['outcome'])
        job.mark_done(None)
    except Cancelled:
        job.mark_failed('Stopped by you.')
    except (AINotConfigured, UnsafeURL, FetchError, AIRefused, ValueError) as error:
        job.mark_failed(str(error))
    except anthropic.AuthenticationError:
        job.mark_failed('The API key was rejected. Check it under Settings.')
    except anthropic.RateLimitError:
        job.mark_failed('The AI provider is rate-limiting this key. Try again in a minute.')
    except anthropic.APIStatusError as error:
        job.mark_failed(f'The AI provider answered {error.status_code}: {error.message}')
    except anthropic.APIConnectionError:
        job.mark_failed('Could not reach the AI provider. Check the connection and try again.')
    except ValidationError as error:
        job.mark_failed('A change could not be saved: ' + '; '.join(
            f'{key}: {", ".join(lines)}' for key, lines in error.message_dict.items()))
    except Exception as error:  # noqa: BLE001 - a job must never take the request or worker down
        log.exception('AI job %s failed', job_id)
        job.mark_failed(f'{error.__class__.__name__}: {error}')
    return job


def cancel(job):
    """ Ask a running job to stop. The runner notices between steps; if it never does (a dead
    thread), the job is failed straight away so nothing spins forever. """
    if not job.is_running:
        return job
    AIJob.objects.filter(pk=job.pk).update(cancel_requested=True)
    job.cancel_requested = True
    if job.is_stale or job.status == AIJob.STATUS_QUEUED:
        job.mark_failed('Stopped by you.')
    return job
