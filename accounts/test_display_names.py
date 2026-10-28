"""Display names: partners see each other's chosen name, never the email."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from couples import services

PASSWORD = "a-long-passphrase-1"
# The 18+ and consent checkboxes every sign-up must tick (accounts/test_consents.py).
TICKED = {box: "on" for box in ["confirm_age", "agree_terms", "agree_sensitive", "agree_transfer"]}


def make_user(email, name=""):
    return get_user_model().objects.create_user(email=email, password=PASSWORD, display_name=name)


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def pair(ann, ben):
    services.create_couple(ann)
    services.redeem_invitation(ben, services.create_invitation(ann))


class RegistrationNameTests(TestCase):
    def setUp(self):
        cache.clear()

    def register(self, name):
        return self.client.post("/accounts/register/", {
            "display_name": name, "email": "new@example.com",
            "password1": PASSWORD, "password2": PASSWORD, **TICKED,
        })

    def test_registration_asks_for_a_display_name(self):
        self.register("  Ann  ")
        self.assertEqual(get_user_model().objects.get().display_name, "Ann")

    def test_display_name_is_required_and_limited(self):
        for name in ["", "   ", "x" * 41]:
            with self.subTest(name=name[:5]):
                self.register(name)
        self.assertFalse(get_user_model().objects.exists())


class PartnerSeesNameNotEmailTests(TestCase):
    def setUp(self):
        self.ann = make_user("ann-private@example.com", "Ann")
        self.ben = make_user("ben-private@example.com", "Benny")
        pair(self.ann, self.ben)

    def test_couple_page_shows_the_partners_name_and_never_their_email(self):
        page = signed_in(self.ann).get("/space/").content.decode()
        self.assertIn("Benny", page)
        self.assertNotIn("ben-private@example.com", page)

    def test_partner_without_a_name_is_shown_neutrally(self):
        get_user_model().objects.filter(pk=self.ben.pk).update(display_name="")
        page = signed_in(self.ann).get("/space/").content.decode()
        self.assertIn("Your partner", page)
        self.assertNotIn("ben-private@example.com", page)

    def test_names_are_escaped(self):
        get_user_model().objects.filter(pk=self.ben.pk).update(display_name="<script>x</script>")
        page = signed_in(self.ann).get("/space/").content.decode()
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)


class ProfileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ann = make_user("ann@example.com", "Ann")

    def test_name_can_be_changed(self):
        client = signed_in(self.ann)
        response = client.post("/accounts/profile/", {"display_name": "Annie"})
        self.assertRedirects(response, "/space/", fetch_redirect_response=False)
        self.ann.refresh_from_db()
        self.assertEqual(self.ann.display_name, "Annie")

    def test_profile_requires_sign_in_and_csrf(self):
        self.assertEqual(Client().get("/accounts/profile/").status_code, 302)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.ann)
        self.assertEqual(strict.post("/accounts/profile/", {"display_name": "Hacked"}).status_code, 403)

    def test_invalid_names_are_refused(self):
        client = signed_in(self.ann)
        for name in ["", "x" * 41]:
            client.post("/accounts/profile/", {"display_name": name})
        self.ann.refresh_from_db()
        self.assertEqual(self.ann.display_name, "Ann")

    def test_account_without_a_name_is_prompted_on_the_couple_page(self):
        get_user_model().objects.filter(pk=self.ann.pk).update(display_name="")
        page = signed_in(self.ann).get("/space/").content.decode()
        self.assertIn('href="/accounts/profile/"', page)
