from django.contrib.auth.models import User
from django.test import TestCase

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