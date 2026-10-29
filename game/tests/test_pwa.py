"""Install and offline: the service worker is served from the site root so it
covers the whole app, every page registers it the same way, and the offline
page it falls back to is public and holds nothing personal. Its caching
rules are tested in tests/js/service-worker.test.js."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from couples import services

PASSWORD = "a-long-passphrase-1"
REGISTER = 'navigator.serviceWorker.register("/service-worker.js", { scope: "/" })'
PUBLIC_PAGES = ["/", "/accounts/login/", "/accounts/register/", "/privacy/", "/offline/"]
MEMBER_PAGES = ["/space/", "/modes/", "/play/?mode=questions", "/accounts/profile/"]


def member_client():
    ann = get_user_model().objects.create_user(email="ann@example.com", password=PASSWORD,
                                               display_name="Annabel")
    services.create_couple(ann)
    client = Client()
    client.force_login(ann)
    return client


class ServiceWorkerTests(TestCase):
    def test_it_is_served_from_the_root_so_it_covers_every_page(self):
        response = Client().get("/service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        source = (Path(settings.BASE_DIR) / "static" / "service-worker.js").read_text(encoding="utf-8")
        self.assertEqual(response.content.decode(), source)

    def test_browsers_always_check_for_a_new_version(self):
        self.assertIn("no-cache", Client().get("/service-worker.js")["Cache-Control"])

    def test_every_page_registers_it_once_for_the_whole_site(self):
        member = member_client()
        for page in PUBLIC_PAGES + MEMBER_PAGES:
            with self.subTest(page):
                client = member if page in MEMBER_PAGES else Client()
                html = client.get(page).content.decode()
                self.assertEqual(html.count(REGISTER), 1)
                self.assertNotIn("/static/service-worker.js", html)

    def test_the_manifest_starts_the_installed_app_at_the_root(self):
        import json

        manifest = json.loads((Path(settings.BASE_DIR) / "static" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["start_url"], manifest["scope"], manifest["display"]), ("/", "/", "standalone"))


class OfflinePageTests(TestCase):
    def test_it_is_public_and_says_what_works_offline(self):
        response = Client().get("/offline/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You're offline")
        self.assertContains(response, "needs a connection")

    def test_it_is_the_same_for_everyone_and_holds_nothing_personal(self):
        # The service worker stores this page, so it must never contain
        # anything about whoever happened to load it.
        anonymous = Client().get("/offline/").content.decode()
        signed_in = member_client().get("/offline/").content.decode()
        self.assertEqual(anonymous.replace(self.csrf(anonymous), ""), signed_in.replace(self.csrf(signed_in), ""))
        for personal in ["Annabel", "ann@example.com", "csrfmiddlewaretoken", "chat-fab"]:
            self.assertNotIn(personal, signed_in)

    @staticmethod
    def csrf(html):
        marker = 'name="csrfmiddlewaretoken" value="'
        if marker not in html:
            return "\0"
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_it_is_reachable_before_accepting_the_consents(self):
        from accounts.testing import without_auto_consent

        with without_auto_consent():
            bob = get_user_model().objects.create_user(email="bob@example.com", password=PASSWORD)
        client = Client()
        client.force_login(bob)
        self.assertEqual(client.get("/offline/").status_code, 200)
        self.assertEqual(client.get("/service-worker.js").status_code, 200)
