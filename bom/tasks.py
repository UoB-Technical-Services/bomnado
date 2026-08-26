""" Celery tasks. Discovered by `bomnado.celery`; run inline when `CELERY_TASK_ALWAYS_EAGER` is set. """
from celery import shared_task


@shared_task
def run_ai_job(job_id):
    """ Do the work of an `AIJob` (see `bom.ai.jobs.run`). """
    from bom.ai.jobs import run
    run(job_id)
