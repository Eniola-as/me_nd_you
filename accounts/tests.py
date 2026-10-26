import os
from io import StringIO

from django.apps import apps
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState
from django.test import TestCase


class UserModelTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def test_project_uses_the_accounts_user_model(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertEqual(self.User._meta.label, "accounts.User")

    def test_users_sign_in_with_email_and_have_no_username(self):
        self.assertEqual(self.User.USERNAME_FIELD, "email")
        self.assertNotIn("username", [f.name for f in self.User._meta.get_fields()])

    def test_create_user_normalises_email_and_hashes_password(self):
        user = self.User.objects.create_user(email="  Ann@Example.COM ", password="a-long-passphrase-1")
        self.assertEqual(user.email, "ann@example.com")
        self.assertNotEqual(user.password, "a-long-passphrase-1")
        self.assertTrue(user.check_password("a-long-passphrase-1"))
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_email_is_required(self):
        with self.assertRaises(ValueError):
            self.User.objects.create_user(email="", password="a-long-passphrase-1")

    def test_email_is_unique_regardless_of_case_in_the_database(self):
        self.User.objects.create_user(email="ann@example.com", password="pw-one-two-three")
        # Bypass the manager's normalisation: the database itself must refuse.
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.User.objects.bulk_create([self.User(email="ANN@example.com")])

    def test_create_superuser(self):
        admin = self.User.objects.create_superuser(email="admin@example.com", password="pw-one-two-three")
        self.assertTrue(admin.is_staff and admin.is_superuser and admin.is_active)

    def test_authenticate_with_email(self):
        self.User.objects.create_user(email="ann@example.com", password="a-long-passphrase-1")
        self.assertIsNotNone(authenticate(email="ANN@example.com".lower(), password="a-long-passphrase-1"))
        self.assertIsNone(authenticate(email="ann@example.com", password="wrong"))

    def test_password_validators_still_apply(self):
        user = self.User(email="ann@example.com")
        with self.assertRaises(ValidationError):
            validate_password("ann@example.com", user)  # Too similar to the email.


class CreateSuperuserCommandTests(TestCase):
    def test_noninteractive_createsuperuser_uses_email(self):
        env = {"DJANGO_SUPERUSER_EMAIL": "boss@example.com", "DJANGO_SUPERUSER_PASSWORD": "pw-one-two-three"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            call_command("createsuperuser", interactive=False, stdout=StringIO())
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertTrue(get_user_model().objects.get(email="boss@example.com").is_superuser)


class UserAdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            email="admin@example.com", password="pw-one-two-three"
        )
        self.client.force_login(self.admin)

    def test_user_admin_pages_render(self):
        for url in [
            f"/{settings.ADMIN_URL}accounts/user/",
            f"/{settings.ADMIN_URL}accounts/user/add/",
            f"/{settings.ADMIN_URL}accounts/user/{self.admin.pk}/change/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_can_add_a_user_by_email(self):
        response = self.client.post(
            f"/{settings.ADMIN_URL}accounts/user/add/",
            {"email": "Ben@Example.com", "password1": "a-long-passphrase-2",
             "password2": "a-long-passphrase-2", "usable_password": "true"},
        )
        self.assertEqual(response.status_code, 302, response.content[:500])
        self.assertTrue(get_user_model().objects.filter(email="ben@example.com").exists())


class AccountsMigrationTests(TestCase):
    def test_models_and_migrations_agree(self):
        # Compared in memory, so no existing database is consulted.
        loader = MigrationLoader(None, ignore_no_migrations=True)
        changes = MigrationAutodetector(
            loader.project_state(), ProjectState.from_apps(apps)
        ).changes(graph=loader.graph)
        self.assertNotIn("accounts", changes)
