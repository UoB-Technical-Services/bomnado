import os
import tempfile

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from bom.models import Attachment, Part, PartSource
from bom.tests.factories import PartFactory, PartSourceFactory, TeamFactory


class MutatingViewsRequirePostTests(TestCase):
    """ Views that create or delete records must refuse GET (405) and only act on POST. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    # --- part create -------------------------------------------------------

    def test_part_create_get_is_not_allowed(self):
        response = self.client.get(reverse('bom:part_editor_create'), {'url': 'M8-NUT', 'team': self.team.id})
        self.assertEqual(response.status_code, 405)
        self.assertFalse(Part.objects.filter(reference='M8-NUT').exists())

    def test_part_create_post_creates_part(self):
        response = self.client.post(reverse('bom:part_editor_create'), {'url': 'm8-nut', 'team': self.team.id})
        part = Part.objects.get(reference='M8-NUT', team=self.team)
        self.assertRedirects(response, reverse('bom:part_editor_update', kwargs={'pk': part.id}),
                             fetch_redirect_response=False)
        self.assertEqual(part.sources.count(), 1)

    def test_part_create_post_for_other_team_is_forbidden(self):
        other_team = TeamFactory()
        response = self.client.post(reverse('bom:part_editor_create'), {'url': 'M8-NUT', 'team': other_team.id})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Part.objects.filter(reference='M8-NUT').exists())

    # --- part duplicate ----------------------------------------------------

    def test_part_duplicate_get_is_not_allowed(self):
        part = PartFactory(team=self.team, picture=None)
        response = self.client.get(reverse('bom:part_duplicate'), {'source_id': part.id})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(Part.objects.count(), 1)

    def test_part_duplicate_post_copies_part_and_sources(self):
        part = PartFactory(team=self.team, picture=None, reference='BOLT')
        PartSourceFactory(part=part, partcode='ABC')

        response = self.client.post(reverse('bom:part_duplicate'), {'source_id': part.id})

        copy = Part.objects.get(reference='BOLT-COPY')
        self.assertRedirects(response, reverse('bom:part_editor_update', kwargs={'pk': copy.id}),
                             fetch_redirect_response=False)
        self.assertEqual(copy.team, self.team)
        self.assertEqual(list(PartSource.objects.filter(part=copy).values_list('partcode', flat=True)), ['ABC-COPY'])
        # The original is untouched.
        self.assertTrue(Part.objects.filter(pk=part.pk, reference='BOLT').exists())

    def test_part_duplicate_post_without_source_is_bad_request(self):
        response = self.client.post(reverse('bom:part_duplicate'), {})
        self.assertEqual(response.status_code, 400)

    def test_part_duplicate_post_for_other_team_is_forbidden(self):
        part = PartFactory(picture=None)  # a team the user is not in
        response = self.client.post(reverse('bom:part_duplicate'), {'source_id': part.id})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Part.objects.count(), 1)

    # --- attachment delete -------------------------------------------------

    def _attachment_for(self, part, media_root):
        attachment = Attachment(content_type=ContentType.objects.get_for_model(part), object_id=part.pk)
        attachment.attachment_file.save('notes.txt', SimpleUploadedFile('notes.txt', b'hello'))
        attachment.save()
        self.assertTrue(os.path.exists(attachment.attachment_file.path))
        return attachment

    def test_attachment_delete_get_is_not_allowed(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            part = PartFactory(team=self.team, picture=None)
            attachment = self._attachment_for(part, media_root)

            response = self.client.get(attachment.delete_link)

            self.assertEqual(response.status_code, 405)
            self.assertTrue(Attachment.objects.filter(pk=attachment.pk).exists())
            self.assertTrue(os.path.exists(attachment.attachment_file.path))

    def test_attachment_delete_post_removes_record_and_file(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            part = PartFactory(team=self.team, picture=None)
            attachment = self._attachment_for(part, media_root)
            path = attachment.attachment_file.path

            response = self.client.post(attachment.delete_link)

            self.assertEqual(response.status_code, 200)
            self.assertFalse(Attachment.objects.filter(pk=attachment.pk).exists())
            self.assertFalse(os.path.exists(path))

    def test_attachment_delete_post_for_other_team_is_forbidden(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            part = PartFactory(picture=None)  # a team the user is not in
            attachment = self._attachment_for(part, media_root)

            response = self.client.post(attachment.delete_link)

            self.assertEqual(response.status_code, 403)
            self.assertTrue(Attachment.objects.filter(pk=attachment.pk).exists())


class PartStartViewTests(TestCase):
    """ The "Part Editor" navigation link must never create records. """

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.client.force_login(self.user)
        self.url = reverse('bom:part_editor')

    def test_redirects_to_first_available_part(self):
        team = TeamFactory(owner=self.user)
        team.users.add(self.user)
        part = PartFactory(team=team, picture=None)
        PartFactory(picture=None)  # someone else's part

        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('bom:part_editor_update', kwargs={'pk': part.id}),
                             fetch_redirect_response=False)

    def test_without_team_redirects_to_teams_page(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('bom:teams'), fetch_redirect_response=False)
        self.assertEqual(Part.objects.count(), 0)

    def test_without_parts_shows_new_part_form_and_creates_nothing(self):
        team = TeamFactory(owner=self.user)
        team.users.add(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/part_editor_empty.html')
        self.assertContains(response, reverse('bom:part_editor_create'))
        self.assertContains(response, team.name)
        self.assertEqual(Part.objects.count(), 0)

    def test_without_parts_shows_pending_error_message_once(self):
        team = TeamFactory(owner=self.user)
        team.users.add(self.user)

        # An empty reference is rejected by the create view, which redirects back here with a message.
        response = self.client.post(reverse('bom:part_editor_create'), {'url': '', 'team': team.id})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

        response = self.client.get(self.url)
        self.assertContains(response, 'Part reference is required.')
        response = self.client.get(self.url)
        self.assertNotContains(response, 'Part reference is required.')
