"""The pages: a landing page for visitors, and the mode and play pages for
signed-in members of a couple space. Nothing works with a secret word."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from couples import services

PASSWORD = "a-long-passphrase-1"


def make_user(email):
    return get_user_model().objects.create_user(email=email, password=PASSWORD)


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


class LandingPageTests(TestCase):
    def test_visitors_see_sign_in_and_create_account(self):
        page = Client().get("/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'href="/accounts/login/"')
        self.assertContains(page, 'href="/accounts/register/"')
        self.assertContains(page, "Sign in")
        self.assertContains(page, "Create account")

    def test_landing_page_keeps_the_app_install_links(self):
        page = Client().get("/")
        self.assertContains(page, "manifest.json")
        self.assertContains(page, "service-worker.js")

    def test_there_is_no_secret_word_form(self):
        page = Client().get("/").content.decode().lower()
        self.assertNotIn("secret", page)
        self.assertNotIn("/api/login/", page)

    def test_members_of_a_couple_go_straight_to_their_space(self):
        ann = make_user("ann@example.com")
        services.create_couple(ann)
        self.assertRedirects(signed_in(ann).get("/"), "/space/", fetch_redirect_response=False)

    def test_signed_in_people_without_a_couple_go_to_their_space_page_to_start_one(self):
        self.assertRedirects(signed_in(make_user("cy@example.com")).get("/"), "/space/",
                             fetch_redirect_response=False)


class GamePageAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ann = make_user("ann@example.com")
        services.create_couple(self.ann)

    def test_visitors_are_sent_to_sign_in(self):
        for url in ["/modes/", "/play/?mode=questions"]:
            response = Client().get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/accounts/login/"), url)

    def test_people_without_a_couple_are_sent_to_their_space_page(self):
        client = signed_in(make_user("cy@example.com"))
        for url in ["/modes/", "/play/?mode=questions"]:
            self.assertRedirects(client.get(url), "/space/", fetch_redirect_response=False)

    def test_members_get_all_six_modes(self):
        page = signed_in(self.ann).get("/modes/")
        for mode in ["questions", "truth", "challenge", "spicy", "mixed", "would"]:
            self.assertContains(page, f'data-mode="{mode}"')

    def test_play_page_runs_on_the_server_room_only(self):
        html = signed_in(self.ann).get("/play/?mode=spicy").content.decode()
        self.assertIn("js/room-client.js", html)
        self.assertIn("/ws/room/questions/", html)
        for gone in ["game-messages.js", "GameMessages", "secret", "/ws/game/", "localStorage.setItem(key",
                     "/api/questions/", "/api/add-custom-question/"]:
            self.assertNotIn(gone, html)


class RemovedRoutesTests(TestCase):
    def test_secret_word_and_unused_endpoints_are_gone(self):
        ann = make_user("ann@example.com")
        services.create_couple(ann)
        client = signed_in(ann)
        for url in ["/api/login/", "/api/questions/questions/", "/api/add-custom-question/",
                    "/api/space/questions/questions/"]:
            self.assertEqual(client.get(url).status_code, 404, url)
            self.assertEqual(client.post(url, {}, content_type="application/json").status_code, 404, url)
