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
        self.assertIn('"questions"', html)  # The shared-deck game for this mode.
        self.assertIn("/ws/room/${game}/", html)
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


class TruthOrDarePageTests(TestCase):
    """The play page runs Truth or Dare as turns on its own room; the other
    modes keep the shared Next deck."""

    def setUp(self):
        self.ann = make_user("ann@example.com")
        services.create_couple(self.ann)
        self.html = signed_in(self.ann).get("/play/?mode=truth").content.decode()

    def test_truth_or_dare_uses_its_own_room(self):
        self.assertIn('"truth_or_dare"', self.html)
        self.assertIn("/ws/room/${game}/${encodeURIComponent(mode)}/", self.html)

    def test_it_has_a_turn_banner_and_its_own_buttons(self):
        for element in ['id="turn-banner"', 'id="card-kind"', 'id="truthBtn"', 'id="dareBtn"', 'id="skipBtn"']:
            self.assertIn(element, self.html)
        for action in ['room.act("choose", { kind: "truth" })', 'room.act("choose", { kind: "dare" })',
                       'room.act("skip")']:
            self.assertIn(action, self.html)

    def test_the_banner_announces_the_random_first_turn(self):
        self.assertIn("Coin toss: you go first", self.html)
        self.assertIn("goes first", self.html)

    def test_custom_questions_say_whether_they_are_a_truth_or_a_dare(self):
        self.assertIn('name="new-kind"', self.html)
        self.assertIn("kind: selectedKind()", self.html)


class QuestionsAnswerPageTests(TestCase):
    """Questions mode: private answers with a simultaneous reveal, on the
    answer-reveal room. Other modes keep the shared Next deck."""

    def setUp(self):
        self.ann = make_user("ann@example.com")
        services.create_couple(self.ann)
        self.client = signed_in(self.ann)
        self.html = self.client.get("/play/?mode=questions").content.decode()

    def test_questions_mode_uses_the_answer_reveal_room(self):
        self.assertIn('<body data-game="answer_reveal"', self.html)
        self.assertIn('const answering = game === "answer_reveal";', self.html)

    def test_it_has_an_answer_box_limited_to_500_characters(self):
        self.assertIn('id="answer-panel"', self.html)
        self.assertRegex(self.html, r'<textarea[^>]*id="answer-text"[^>]*maxlength="500"')
        self.assertIn('id="answerBtn"', self.html)

    def test_an_answer_names_the_card_it_is_for(self):
        self.assertIn('room.act("answer", { text, card: answerCard })', self.html)

    def test_it_says_when_the_partner_has_answered_and_shows_the_reveal(self):
        self.assertIn("has answered", self.html)
        self.assertIn("Waiting for", self.html)
        for element in ['id="reveal"', 'id="reveal-mine"', 'id="reveal-partner"', 'id="reveal-partner-name"']:
            self.assertIn(element, self.html)
        # The reveal box is a grid, which would override the hidden attribute.
        self.assertIn("#reveal[hidden]", self.html)

    def test_next_and_the_rest_stay(self):
        for button in ['id="nextBtn"', 'id="addBtn"', 'id="resetBtn"', 'id="switchBtn"']:
            self.assertIn(button, self.html)

    def test_the_mode_menu_explains_it(self):
        page = self.client.get("/modes/").content.decode()
        self.assertEqual(page.count("Answer privately, reveal together"), 1)


class OptimisticAnswerReactionTests(TestCase):
    def test_your_reaction_to_an_answer_shows_at_once_and_is_undone_if_refused(self):
        ann = make_user("ann@example.com")
        services.create_couple(ann)
        html = signed_in(ann).get("/play/?mode=questions").content.decode()
        self.assertIn("const answerReactionTaps = {};", html)
        self.assertIn("Couldn't react: ", html.replace("&#x27;", "'"))
        self.assertIn("tap.stale = true", html)
