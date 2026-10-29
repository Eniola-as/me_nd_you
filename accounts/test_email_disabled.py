from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core import mail
from django.core.mail import EmailMessage
from django.test import Client, TestCase, override_settings


PASSWORD = "a-long-passphrase-1"
TICKED = {box: "on" for box in ["confirm_age", "agree_terms", "agree_sensitive", "agree_transfer"]}
NO_EMAIL = override_settings(
    EMAIL_ENABLED=False,
    EMAIL_PROVIDER="",
    EMAIL_BACKEND="accounts.email_backend.DisabledEmailBackend",
)


@NO_EMAIL
class DisabledEmailBetaTests(TestCase):
    def setUp(self):
        mail.outbox.clear()

    def register(self):
        return self.client.post("/accounts/register/", {
            "display_name": "Ann",
            "email": "ann@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
            **TICKED,
        })

    def test_the_backend_refuses_to_print_email_contents(self):
        with self.assertRaises(ImproperlyConfigured):
            EmailMessage("Reset", "Sensitive reset link", None, ["ann@example.com"]).send()
        self.assertEqual(mail.outbox, [])

    def test_registration_works_without_sending_verification(self):
        response = self.register()
        self.assertRedirects(response, "/space/", fetch_redirect_response=False)
        user = get_user_model().objects.get(email="ann@example.com")
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(mail.outbox, [])
        self.assertNotContains(self.client.get("/space/"), "Please verify your email")

    def test_signup_explains_email_and_recovery_limits(self):
        page = Client().get("/accounts/register/")
        self.assertContains(page, "Email delivery is disabled for this beta.")
        self.assertContains(page, "password recovery is unavailable")

    def test_login_does_not_offer_an_unavailable_reset_link(self):
        page = Client().get("/accounts/login/")
        self.assertContains(page, "Password recovery is unavailable")
        self.assertNotContains(page, 'href="/accounts/password/reset/"')

    def test_password_reset_pages_are_explicitly_unavailable(self):
        for method in ["get", "post"]:
            with self.subTest(method):
                response = getattr(Client(), method)("/accounts/password/reset/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Password reset unavailable")
                self.assertContains(response, "password-reset links cannot be sent")
        self.assertEqual(mail.outbox, [])

    def test_reset_confirmation_does_not_process_tokens(self):
        response = Client().post("/accounts/password/reset/confirm/", {"token": "anything"})
        self.assertContains(response, "Password reset unavailable")
        self.assertEqual(mail.outbox, [])

    def test_email_verification_endpoint_reports_disabled_delivery(self):
        response = Client().get("/accounts/verify/")
        self.assertContains(response, "Email delivery is disabled for this beta")
        self.assertNotContains(response, "verify-form")
        self.assertEqual(mail.outbox, [])
