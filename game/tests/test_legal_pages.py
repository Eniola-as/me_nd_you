"""Privacy policy and terms pages, the footer that links them, and the
self-hosted font (no page loads anything from Google)."""

import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings

from couples import services
from game.tests.test_settings import PRODUCTION_ENV
from game.tests.utils import SETTINGS_ENV_KEYS, load_settings

PASSWORD = "a-long-passphrase-1"
FONT_DIR = Path(settings.BASE_DIR) / "static" / "fonts"


def member_client():
    ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD)
    services.create_couple(ann)
    client = Client()
    client.force_login(ann)
    return client


PUBLIC_PAGES = ["/", "/accounts/login/", "/accounts/register/", "/accounts/password/reset/", "/privacy/", "/terms/"]
MEMBER_PAGES = ["/space/", "/modes/", "/play/?mode=questions", "/play/?mode=truth", "/accounts/profile/"]


@override_settings(PRIVACY_CONTACT_EMAIL="privacy@example.com")
class LegalPagesTests(TestCase):
    def test_both_pages_are_public(self):
        for page, heading in [("/privacy/", "Privacy Policy"), ("/terms/", "Terms of Use")]:
            with self.subTest(page):
                response = Client().get(page)
                self.assertContains(response, f"<h1>{heading}</h1>", html=True)

    def test_the_contact_email_and_policy_version_come_from_settings(self):
        for page in ["/privacy/", "/terms/"]:
            with self.subTest(page):
                response = Client().get(page)
                self.assertContains(response, "privacy@example.com")
                self.assertContains(response, settings.POLICY_VERSION)

    @override_settings(PRIVACY_CONTACT_EMAIL="")
    def test_an_unset_contact_email_is_shown_as_missing_not_blank(self):
        self.assertContains(Client().get("/privacy/"), "[contact email not set yet]")

    def test_a_draft_version_shows_a_draft_notice(self):
        with override_settings(POLICY_VERSION="draft-1"):
            self.assertContains(Client().get("/privacy/"), "Draft: under review")
        with override_settings(POLICY_VERSION="2026-11-01"):
            self.assertNotContains(Client().get("/privacy/"), "Draft: under review")

    def test_encryption_is_described_accurately(self):
        text = re.sub(r"<[^>]+>", "", Client().get("/privacy/").content.decode())
        self.assertIn("not end-to-end encryption", text)
        claims = re.findall(r"[^.]*end-to-end[^.]*\.", text)
        self.assertTrue(claims)
        self.assertTrue(all("not" in claim for claim in claims), claims)

    def test_the_owner_notes_are_not_published(self):
        for page in ["/privacy/", "/terms/"]:
            self.assertNotContains(Client().get(page), "Notes for the owner")


class FooterTests(TestCase):
    def test_every_page_links_to_the_privacy_policy_and_terms(self):
        member = member_client()
        for page in PUBLIC_PAGES + MEMBER_PAGES:
            with self.subTest(page):
                client = member if page in MEMBER_PAGES else Client()
                html = client.get(page).content.decode()
                footer = html[html.index('<footer class="site-footer"'):]
                self.assertIn('href="/privacy/"', footer)
                self.assertIn('href="/terms/"', footer)


class SelfHostedFontTests(TestCase):
    def test_no_page_loads_anything_from_google(self):
        member = member_client()
        for page in PUBLIC_PAGES + MEMBER_PAGES:
            with self.subTest(page):
                client = member if page in MEMBER_PAGES else Client()
                html = client.get(page).content.decode()
                self.assertNotIn("fonts.googleapis.com", html)
                self.assertNotIn("fonts.gstatic.com", html)
                self.assertIn("/static/fonts/outfit-latin.woff2", html)

    def test_the_font_files_and_their_license_ship_with_the_app(self):
        for name in ["outfit-latin.woff2", "outfit-latin-ext.woff2"]:
            self.assertEqual((FONT_DIR / name).read_bytes()[:4], b"wOF2", name)
        license_text = (FONT_DIR / "OFL.txt").read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", license_text)
        self.assertIn("The Outfit Project Authors", license_text)

    def test_nothing_in_the_templates_or_static_files_points_at_google_fonts(self):
        roots = [Path(settings.BASE_DIR) / d for d in ["accounts", "couples", "game", "chat", "static"]]
        hits = [str(p) for root in roots for p in root.rglob("*") if p.suffix in {".html", ".js", ".css", ".json"}
                and "fonts.g" in p.read_text(encoding="utf-8", errors="ignore")]
        self.assertEqual(hits, [])


class ContactEmailSettingTests(SimpleTestCase):
    def test_the_contact_email_comes_from_the_environment(self):
        values = load_settings({"PRIVACY_CONTACT_EMAIL": "hello@example.com"}, ["PRIVACY_CONTACT_EMAIL"])
        self.assertEqual(values["PRIVACY_CONTACT_EMAIL"], "hello@example.com")

    def test_a_deploy_check_warns_while_it_is_unset(self):
        env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        env.update({k: v for k, v in PRODUCTION_ENV.items() if k != "PRIVACY_CONTACT_EMAIL"})
        result = subprocess.run([sys.executable, "manage.py", "check", "--deploy"], cwd=settings.BASE_DIR,
                                env=env, capture_output=True, text=True)
        self.assertIn("accounts.W004", result.stdout + result.stderr)

    def test_the_render_blueprint_takes_it_from_the_dashboard(self):
        render_yaml = (Path(settings.BASE_DIR) / "render.yaml").read_text()
        self.assertRegex(render_yaml, r"key: PRIVACY_CONTACT_EMAIL\s+sync: false")
