import json
import mimetypes
import re
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings

from couples import services

from .utils import load_settings

STATIC_DIR = Path(settings.BASE_DIR) / "static"
PRODUCTION_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


class StaticStorageSettingsTests(SimpleTestCase):
    def test_production_uses_hashed_compressed_storage(self):
        values = load_settings({}, ["STORAGES"])
        self.assertEqual(values["STORAGES"]["staticfiles"]["BACKEND"], PRODUCTION_STORAGE)

    def test_json_files_are_not_served_as_web_manifests(self):
        self.assertEqual(mimetypes.guess_type("data.json")[0], "application/json")


class CollectedPagesRenderTests(TestCase):
    """With hashed storage, a {% static %} reference to a missing file raises
    an error, so rendering every page after collectstatic proves they exist."""

    def setUp(self):
        self.static_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.static_root)

    def test_pages_render_with_production_storage(self):
        storages = {**settings.STORAGES, "staticfiles": {"BACKEND": PRODUCTION_STORAGE}}
        with override_settings(STATIC_ROOT=self.static_root, STORAGES=storages):
            call_command("collectstatic", interactive=False, verbosity=0, stdout=StringIO())
            for url in ["/", "/accounts/login/", "/accounts/register/", "/invite/"]:
                with self.subTest(url=url):
                    self.assertEqual(Client().get(url).status_code, 200)
            member = get_user_model().objects.create_user(email="ann@example.com", password="pw-for-tests-1")
            services.create_couple(member)
            self.client.force_login(member)
            for url in ["/space/", "/modes/", "/play/?mode=questions"]:
                with self.subTest(url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)


class WebManifestTests(SimpleTestCase):
    def setUp(self):
        self.manifest = json.loads((STATIC_DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_identifies_the_app(self):
        self.assertEqual(self.manifest["id"], "/")
        self.assertEqual(self.manifest["scope"], "/")

    def test_manifest_icons_exist_as_png(self):
        for icon in self.manifest["icons"]:
            with self.subTest(src=icon["src"]):
                path = STATIC_DIR / icon["src"].removeprefix("/static/")
                self.assertTrue(path.exists())
                self.assertEqual(icon["type"], "image/png")
                self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))

    def test_manifest_has_a_maskable_icon(self):
        self.assertTrue(any("maskable" in i.get("purpose", "") for i in self.manifest["icons"]))


class ServiceWorkerTests(SimpleTestCase):
    def test_precached_static_files_exist(self):
        sw = (STATIC_DIR / "service-worker.js").read_text(encoding="utf-8")
        for url in re.findall(r'"(/static/[^"]+)"', sw):
            with self.subTest(url=url):
                self.assertTrue((STATIC_DIR / url.removeprefix("/static/")).exists())
