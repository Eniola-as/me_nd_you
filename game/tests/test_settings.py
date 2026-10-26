import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .utils import SETTINGS_ENV_KEYS, load_settings

PRODUCTION_ENV = {
    "DEBUG": "False",
    "ALLOWED_HOSTS": "me-nd-you.onrender.com",
    "SECRET_KEY": "test-only-fake-key-not-a-secret-for-deploy-check-0123456789",
}


class DeploymentFilesTests(SimpleTestCase):
    root = Path(settings.BASE_DIR)

    def test_requirements_are_plain_utf8(self):
        raw = (self.root / "requirements.txt").read_bytes()
        self.assertFalse(raw.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")))
        raw.decode("utf-8")

    def test_requirements_skip_unused_native_packages(self):
        names = {
            line.split("==")[0].strip().lower()
            for line in (self.root / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        self.assertTrue(names.isdisjoint({"mysqlclient", "pymysql", "pillow"}))
        self.assertIn("django", names)

    def test_render_blueprint_contains_no_secret_values(self):
        render_yaml = (self.root / "render.yaml").read_text()
        # SECRET_KEY must be set in the Render dashboard, never in the repo.
        self.assertRegex(render_yaml, r"key: SECRET_KEY\s+sync: false")
        # The DB_* variables were never read by settings.py.
        self.assertNotRegex(render_yaml, r"key: DB_")

    def test_render_blueprint_pins_python_the_supported_way(self):
        render_yaml = (self.root / "render.yaml").read_text()
        self.assertNotIn("pythonVersion", render_yaml)
        self.assertIn("runtime: python", render_yaml)
        self.assertIn("key: PYTHON_VERSION", render_yaml)


class NoInertSecuritySettingsTests(SimpleTestCase):
    def test_settings_without_an_installed_consumer_are_absent(self):
        # CSP_* needs django-csp; SECURE_BROWSER_XSS_FILTER was removed in Django 4.0.
        inert = [
            name
            for name in dir(settings)
            if name.startswith("CSP_") or name == "SECURE_BROWSER_XSS_FILTER"
        ]
        self.assertEqual(inert, [])


class AdminUrlTests(SimpleTestCase):
    def admin_index(self, extra_env):
        env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        env.update({"SECRET_KEY": "test-key", "DEBUG": "True", **extra_env})
        script = (
            "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', "
            "'me_nd_you.settings'); django.setup(); from django.urls import reverse; "
            "print(reverse('admin:index'))"
        )
        return subprocess.run(
            [sys.executable, "-c", script], cwd=settings.BASE_DIR, env=env,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_admin_lives_at_admin_by_default(self):
        self.assertEqual(self.admin_index({}), "/admin/")

    def test_admin_path_can_be_moved_by_environment(self):
        self.assertEqual(self.admin_index({"ADMIN_URL": "backstage-7f3k/"}), "/backstage-7f3k/")


class HttpsSettingsTests(SimpleTestCase):
    def test_production_trusts_render_proxy_and_secures_cookies(self):
        values = load_settings(
            PRODUCTION_ENV,
            [
                "SECURE_PROXY_SSL_HEADER",
                "SECURE_SSL_REDIRECT",
                "SESSION_COOKIE_SECURE",
                "CSRF_COOKIE_SECURE",
                "CSRF_TRUSTED_ORIGINS",
            ],
        )
        self.assertEqual(values["SECURE_PROXY_SSL_HEADER"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertTrue(values["SECURE_SSL_REDIRECT"])
        self.assertTrue(values["SESSION_COOKIE_SECURE"])
        self.assertTrue(values["CSRF_COOKIE_SECURE"])
        self.assertIn("https://me-nd-you.onrender.com", values["CSRF_TRUSTED_ORIGINS"])

    def test_local_development_does_not_force_https(self):
        values = load_settings({"DEBUG": "True"}, ["SECURE_SSL_REDIRECT"])
        self.assertFalse(values["SECURE_SSL_REDIRECT"])

    def test_deploy_check_reports_no_warnings(self):
        env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        env.update(PRODUCTION_ENV)
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


class AllowedHostsTests(SimpleTestCase):
    def test_render_external_hostname_is_allowed(self):
        values = load_settings(
            {"ALLOWED_HOSTS": "", "RENDER_EXTERNAL_HOSTNAME": "me-nd-you.onrender.com"},
            ["ALLOWED_HOSTS"],
        )
        self.assertIn("me-nd-you.onrender.com", values["ALLOWED_HOSTS"])

    def test_render_blueprint_allows_the_real_domain(self):
        render_yaml = (Path(settings.BASE_DIR) / "render.yaml").read_text()
        self.assertNotIn("your-render-app.onrender.com", render_yaml)
        self.assertIn("me-nd-you.onrender.com", render_yaml)
