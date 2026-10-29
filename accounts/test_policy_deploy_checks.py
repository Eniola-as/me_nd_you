"""Deploy safety (option (a), owner 2026-10-29): with DEBUG off, `check
--deploy` refuses a draft policy version, a published privacy notice that
still has [CHECK] or [DEPENDS ON] notes, and a missing privacy contact."""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from accounts.checks import check_policy, published_notice_text

FINAL = dict(DEBUG=False, POLICY_VERSION="beta-2026-10-29-4", PRIVACY_CONTACT_EMAIL="privacy@example.com")
CLEAN_NOTICE = "Beta Privacy Notice. Contact privacy@example.com. Hosting: Render, Oregon, USA."


def ids(errors):
    return sorted(error.id for error in errors)


@override_settings(**FINAL)
class PolicyDeployCheckTests(SimpleTestCase):
    def run_check(self, notice=CLEAN_NOTICE):
        with mock.patch("accounts.checks.published_notice_text", return_value=notice):
            return check_policy(None)

    def test_a_finished_policy_passes(self):
        self.assertEqual(self.run_check(), [])

    @override_settings(POLICY_VERSION="draft-2026-10-28")
    def test_a_draft_policy_version_is_an_error(self):
        self.assertEqual(ids(self.run_check()), ["accounts.E001"])

    def test_check_notes_in_the_published_notice_are_an_error(self):
        errors = self.run_check(CLEAN_NOTICE + " [CHECK: provisional; confirm the region]")
        self.assertEqual(ids(errors), ["accounts.E002"])
        self.assertIn("1", errors[0].msg)

    def test_depends_on_notes_in_the_published_notice_are_an_error(self):
        self.assertEqual(ids(self.run_check(CLEAN_NOTICE + " [DEPENDS ON: comfort feature]")), ["accounts.E003"])

    @override_settings(PRIVACY_CONTACT_EMAIL="")
    def test_a_missing_privacy_contact_is_an_error(self):
        self.assertEqual(ids(self.run_check()), ["accounts.E004"])

    @override_settings(DEBUG=True, POLICY_VERSION="draft-1", PRIVACY_CONTACT_EMAIL="")
    def test_local_development_is_not_blocked(self):
        self.assertEqual(self.run_check(CLEAN_NOTICE + " [CHECK: x]"), [])


@override_settings(**FINAL)
class PublishedNoticeTextTests(SimpleTestCase):
    def test_it_reads_the_notice_as_published_with_the_settings_filled_in(self):
        text = published_notice_text()
        self.assertIn("Beta Privacy Notice", text)
        self.assertIn("privacy@example.com", text)
        self.assertNotIn("{{", text)

    @override_settings(EMAIL_PROVIDER="brevo")
    def test_the_configured_provider_is_disclosed(self):
        self.assertIn("Brevo", published_notice_text())

    def test_unknown_provider_and_database_details_are_disclosed_without_guessing(self):
        notice = published_notice_text()
        self.assertIn("account email delivery is disabled", notice)
        self.assertIn("web service and PostgreSQL database are in Oregon, USA", notice)
        self.assertIn("14-day log retention", notice)
        self.assertIn("5 GB of bandwidth", notice)
        self.assertNotIn("[CHECK", notice)
        self.assertNotIn("[DEPENDS ON", notice)
