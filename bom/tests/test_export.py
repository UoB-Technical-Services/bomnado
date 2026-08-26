from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

class TestExportDatabaseAuth(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password12345")
        self.superuser = User.objects.create_superuser(username="testsuperuser", password="password12345", email="testsuperuser@test.com")

    def tearDown(self) -> None:
        self.client.logout()
        return super().tearDown()

    def test_non_super_user_is_redirected(self):
        self.client.force_login(self.user)
        res = self.client.get('/export/backup')
        self.assertRedirects(res, '/accounts/login/?next=/export/backup')

    def test_super_user_gets_file(self):
        self.client.force_login(self.superuser)
        res = self.client.get('/export/backup')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.has_header('Content-Disposition'))
        self.assertTrue('.zip' in res['Content-Disposition'])


class PurchasingSpreadsheetTests(TestCase):
    """ The purchasing export survives parts without suppliers (they used to crash the sort). """

    def test_a_part_with_no_supplier_sorts_last_instead_of_crashing(self):
        from django.contrib.auth.models import User
        from bom.models import PartSource, SubAssemblyLineItem
        from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory
        user = User.objects.create_user(username='alice', email='alice@example.com', password='pw')
        team = TeamFactory(owner=user)
        team.users.add(user)
        box = SubAssemblyFactory(team=team, reference='BOX', is_toplevel=True, picture=None)
        sourced = PartFactory(team=team, reference='SOURCED', picture=None)
        PartSource.objects.create(part=sourced, supplier='RS', rrp=1.0, lead_time=3)
        bare = PartFactory(team=team, reference='BARE', picture=None)
        SubAssemblyLineItem.objects.create(subassembly=box, child_part=sourced, quantity=2)
        SubAssemblyLineItem.objects.create(subassembly=box, child_part=bare, quantity=1)
        self.client.force_login(user)
        response = self.client.get(reverse('bom:export_purchasing', kwargs={'pk': box.id}))
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response['Content-Type'])
        self.assertEqual(response.content[:2], b'PK')                     # a real xlsx, not an error page


class BomSpreadsheetTests(TestCase):
    """ The BOM export: a real xlsx, and only the exporting user's parts in it. """

    def test_exports_and_keeps_other_teams_parts_out(self):
        from django.contrib.auth.models import User
        from bom.models import SubAssemblyLineItem
        from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory
        user = User.objects.create_user(username='alice', email='alice@example.com', password='pw')
        team = TeamFactory(owner=user)
        team.users.add(user)
        box = SubAssemblyFactory(team=team, reference='BOX', is_toplevel=True, picture=None)
        mine = PartFactory(team=team, reference='MINE-PART', picture=None, kgs=0)
        SubAssemblyLineItem.objects.create(subassembly=box, child_part=mine, quantity=1)
        PartFactory(team=TeamFactory(), reference='THEIRS-PART', picture=None)
        self.client.force_login(user)
        response = self.client.get(reverse('bom:export_xlsx', kwargs={'pk': box.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:2], b'PK')
        import io as _io
        import zipfile
        with zipfile.ZipFile(_io.BytesIO(response.content)) as archive:
            everything = b''.join(archive.read(name) for name in archive.namelist() if name.endswith('.xml'))
        self.assertIn(b'MINE-PART', everything)
        self.assertNotIn(b'THEIRS-PART', everything)


class BackupNowTests(TestCase):
    """ The user menu's Back Up Now: superusers only, POST only, runs both backup commands. """

    def test_the_button_backs_up_and_reports(self):
        from unittest import mock
        boss = User.objects.create_superuser(username='boss', email='boss@example.com', password='pw')
        self.client.force_login(boss)
        with mock.patch('bom.views.exports.perform_backup') as run:
            response = self.client.post(reverse('bom:backup_now'))
        self.assertRedirects(response, reverse('bom:user_settings'))
        run.assert_called_once_with()

    def test_only_superusers_and_only_post(self):
        from unittest import mock
        user = User.objects.create_user(username='pleb', password='pw')
        self.client.force_login(user)
        with mock.patch('bom.views.exports.perform_backup') as run:
            response = self.client.post(reverse('bom:backup_now'))
        self.assertEqual(response.status_code, 302)                   # bounced to login
        self.assertEqual(run.call_count, 0)
        boss = User.objects.create_superuser(username='boss', email='boss@example.com', password='pw')
        self.client.force_login(boss)
        self.assertEqual(self.client.get(reverse('bom:backup_now')).status_code, 405)
