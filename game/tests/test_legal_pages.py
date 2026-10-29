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
from django.utils.html import strip_tags

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


PUBLIC_PAGES = ["/", "/accounts/login/", "/accounts/register/", "/accounts/password/reset/", "/privacy/"]
MEMBER_PAGES = ["/space/", "/modes/", "/play/?mode=questions", "/play/?mode=truth", "/accounts/profile/"]


@override_settings(PRIVACY_CONTACT_EMAIL="privacy@example.com")
class LegalPagesTests(TestCase):
    def test_the_beta_privacy_notice_is_public(self):
        response = Client().get("/privacy/")
        self.assertContains(response, "<h1>Beta Privacy Notice</h1>", html=True)
        self.assertContains(response, "Me &amp; You is in beta.")

    def test_it_covers_everything_a_beta_tester_needs_to_know(self):
        text = " ".join(strip_tags(Client().get("/privacy/").content.decode()).split())
        for heading in ["What we collect", "Who can see it", "Where it's processed", "How long we keep it",
                        "Your choices", "Beta limits", "Playing safely"]:
            self.assertIn(heading, text)
        self.assertIn("Adewale Saheed", text)
        self.assertIn("We reply within 30 days.", text)
        self.assertIn("Profile → \"Delete my account\"", text)
        self.assertIn("Never your email address.", text)
        self.assertIn("Either partner can skip a prompt or stop playing at any time.", text)
        self.assertIn("not relationship, medical or psychological advice.", text)
        self.assertIn("web service and PostgreSQL database are in Oregon, USA", text)
        self.assertIn("web service and PostgreSQL database are in Oregon, USA", text)
        self.assertIn("1 GB limit, no backups, expires 30 days after creation", text)
        self.assertIn("14-day log retention", text)
        self.assertIn("5 GB of bandwidth", text)
        self.assertIn("$0.15/GB", text)
        self.assertIn("Email delivery is disabled for this beta", text)
        self.assertIn("password recovery is unavailable", text.lower())

    def test_the_unpublished_drafts_stay_unpublished(self):
        self.assertEqual(Client().get("/terms/").status_code, 404)
        html = Client().get("/privacy/").content.decode()
        for draft_only in ["Terms of Use", "Notes for the owner", "Legal basis"]:
            self.assertNotIn(draft_only, html)

    def test_the_contact_email_and_policy_version_come_from_settings(self):
        response = Client().get("/privacy/")
        self.assertContains(response, "privacy@example.com")
        self.assertContains(response, settings.POLICY_VERSION)

    @override_settings(EMAIL_PROVIDER="postmark")
    def test_the_email_provider_is_named_from_settings(self):
        text = strip_tags(Client().get("/privacy/").content.decode())
        self.assertIn("Postmark", text)
        self.assertNotIn("email provider not chosen yet", text)

    @override_settings(EMAIL_PROVIDER="")
    def test_an_unconfigured_email_provider_is_disclosed_as_disabled(self):
        text = strip_tags(Client().get("/privacy/").content.decode())
        self.assertIn("no email provider is configured, so account email delivery is disabled", text)
        self.assertIn("Email contents are not sent or written to Render logs", text)
        self.assertNotIn("[CHECK", text)

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



class FooterTests(TestCase):
    def test_every_page_links_to_the_privacy_notice_and_says_beta(self):
        member = member_client()
        for page in PUBLIC_PAGES + MEMBER_PAGES:
            with self.subTest(page):
                client = member if page in MEMBER_PAGES else Client()
                # follow: a second play mode redirects to the couple's mode (play.modes).
                html = client.get(page, follow=True).content.decode()
                footer = html[html.index('<footer class="site-footer"'):]
                self.assertIn('href="/privacy/"', footer)
                self.assertIn("Beta", footer)
                self.assertNotIn('href="/terms/"', html)

    def test_the_landing_and_sign_up_pages_say_it_is_a_beta(self):
        for page in ["/", "/accounts/register/"]:
            with self.subTest(page):
                self.assertContains(Client().get(page), 'class="beta-label"')

    def test_sign_up_displays_the_play_safety_rules(self):
        response = Client().get("/accounts/register/")
        self.assertContains(response, "Adults 18+ only.")
        self.assertContains(response, "either partner can skip or stop at any time.")
        self.assertContains(response, "not relationship, medical or psychological advice.")
        self.assertContains(response, 'href="/privacy/#playing-safely"')


class SelfHostedFontTests(TestCase):
    def test_no_page_loads_anything_from_google(self):
        member = member_client()
        for page in PUBLIC_PAGES + MEMBER_PAGES:
            with self.subTest(page):
                client = member if page in MEMBER_PAGES else Client()
                # follow: a second play mode redirects to the couple's mode (play.modes).
                html = client.get(page, follow=True).content.decode()
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

    def test_a_deploy_check_refuses_while_it_is_unset(self):
        # An error since the deploy-safety change (accounts.E004; it was a warning).
        env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        env.update({k: v for k, v in PRODUCTION_ENV.items() if k != "PRIVACY_CONTACT_EMAIL"})
        result = subprocess.run([sys.executable, "manage.py", "check", "--deploy"], cwd=settings.BASE_DIR,
                                env=env, capture_output=True, text=True)
        self.assertIn("accounts.E004", result.stdout + result.stderr)
        self.assertNotEqual(result.returncode, 0)

    def test_the_render_blueprint_takes_it_from_the_dashboard(self):
        render_yaml = (Path(settings.BASE_DIR) / "render.yaml").read_text()
        self.assertRegex(render_yaml, r"key: PRIVACY_CONTACT_EMAIL\s+sync: false")
