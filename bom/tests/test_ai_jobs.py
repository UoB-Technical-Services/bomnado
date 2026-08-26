""" Turns as jobs: timing, stopping, presumed-dead reaping, and the activity page. """
import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from bom.ai import chat, jobs
from bom.models import AIJob, AIMessage, AIThread, UserAISettings
from bom.tests.factories import TeamFactory

KEY = 'sk-ant-api03-' + 'x' * 40 + 'wxyz'


class JobControlTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)
        config = UserAISettings(user=self.user)
        config.api_key = KEY
        config.save()
        self.user.refresh_from_db()
        self.thread = AIThread.objects.create(user=self.user, team=self.team, title='Bolts')
        AIMessage.objects.create(thread=self.thread, role='user', content=[{'type': 'text', 'text': 'Make a bolt'}])

    def running_job(self, **extra):
        job = AIJob.objects.create(user=self.user, team=self.team, content_object=self.thread, **extra)
        job.mark_running()
        return job

    def status(self):
        return self.client.get(reverse('bom:ai_chat_status', kwargs={'thread_id': self.thread.id})).content.decode()


class TimingTests(JobControlTestCase):

    def test_rerun_does_not_show_a_negative_time(self):
        job = self.running_job()
        job.mark_done()
        job.mark_running()  # started again, `finished` cleared
        self.assertGreaterEqual(job.seconds_running, 0)
        self.assertIsNone(job.finished)

    def test_quiet_jobs_are_presumed_dead_and_retryable(self):
        job = self.running_job()
        AIJob.objects.filter(pk=job.pk).update(progress_at=now() - AIJob.STALE_AFTER - datetime.timedelta(seconds=1))
        html = self.status()
        self.assertIn('stopped without finishing', html)
        self.assertIn('Try again', html)
        self.assertEqual(AIJob.objects.get(pk=job.pk).status, AIJob.STATUS_FAILED)


class StopTests(JobControlTestCase):

    def test_stop_marks_a_dead_job_failed_at_once(self):
        job = self.running_job()
        AIJob.objects.filter(pk=job.pk).update(progress_at=now() - AIJob.STALE_AFTER - datetime.timedelta(seconds=1))
        html = self.client.post(reverse('bom:ai_chat_stop', kwargs={'thread_id': self.thread.id})).content.decode()
        self.assertIn('Stopped by you.', html)
        self.assertEqual(AIJob.objects.get(pk=job.pk).status, AIJob.STATUS_FAILED)

    def test_stop_on_a_live_job_is_noticed_by_the_runner(self):
        job = self.running_job()
        jobs.cancel(job)
        self.assertEqual(AIJob.objects.get(pk=job.pk).status, AIJob.STATUS_RUNNING)  # the runner will notice
        with self.assertRaises(chat.Cancelled):
            chat.check_cancel(job)
        # The runner turns it into a stopped job, and the window says so.
        with mock.patch('bom.ai.jobs.run_turn', side_effect=chat.Cancelled('Stopped.')):
            jobs.run(job.id)
        self.assertEqual(AIJob.objects.get(pk=job.pk).error, 'Stopped by you.')
        self.assertIn('Stopped by you.', self.status())

    def test_stop_is_private_and_idempotent(self):
        job = self.running_job()
        job.mark_done()
        self.assertIs(jobs.cancel(job), job)
        self.assertEqual(AIJob.objects.get(pk=job.pk).status, AIJob.STATUS_DONE)
        self.client.force_login(User.objects.create_user('bob', 'bob@example.com', 'password123'))
        self.assertEqual(self.client.post(reverse('bom:ai_job_cancel', kwargs={'job_id': job.id})).status_code, 403)


class ActivityPageTests(JobControlTestCase):

    def test_lists_running_with_stop_and_recent(self):
        running = self.running_job()
        running.note_progress('search_parts: bolt')
        done = AIJob.objects.create(user=self.user, team=self.team, content_object=self.thread, cost=0.0123,
                                    outcome={'touched': [{'model': 'part', 'id': 1, 'reference': 'BOLT', 'what': 'created'}]})
        done.mark_running()
        done.mark_done()
        html = self.client.get(reverse('bom:ai_jobs')).content.decode()
        self.assertIn('search_parts: bolt', html)
        self.assertIn(reverse('bom:ai_job_cancel', kwargs={'job_id': running.id}), html)
        self.assertIn(f'data-ai-thread="{self.thread.id}"', html)
        self.assertIn('Changed: BOLT', html)
        self.assertIn('$0.012', html)
        # Stop from the page.
        self.client.post(reverse('bom:ai_job_cancel', kwargs={'job_id': running.id}))
        self.assertTrue(AIJob.objects.get(pk=running.pk).cancel_requested)
        # The budget button in the top bar points here.
        self.assertIn(f'href="{reverse("bom:ai_jobs")}"', html)

    def test_clear_hides_finished_jobs_but_keeps_the_spend(self):
        running = self.running_job()
        done = AIJob.objects.create(user=self.user, team=self.team, content_object=self.thread, cost=1.5)
        done.mark_running()
        done.mark_done()
        before = self.user.ai_settings.spend_this_month()
        self.client.post(reverse('bom:ai_jobs_clear'))
        html = self.client.get(reverse('bom:ai_jobs')).content.decode()
        self.assertIn(reverse('bom:ai_job_cancel', kwargs={'job_id': running.id}), html)  # still running, still shown
        self.assertIn('Nothing yet.', html)
        self.assertTrue(AIJob.objects.get(pk=done.pk).cleared)
        self.assertEqual(self.user.ai_settings.spend_this_month(), before)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('bom:ai_jobs')).status_code, 302)
