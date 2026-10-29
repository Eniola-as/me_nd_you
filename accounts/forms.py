from django import forms
from django.contrib.auth.forms import (
    AdminUserCreationForm,
    AuthenticationForm,
    BaseUserCreationForm,
    PasswordResetForm,
    UserChangeForm,
)

from django.utils.safestring import mark_safe

from . import emails

from .legal import email_provider_name
from .models import Consent, User


class UserCreationForm(AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("email",)


class UserEditForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class DisplayNameField(forms.CharField):
    """1-40 characters after trimming; partners see this, not the email."""

    def __init__(self, **kwargs):
        super().__init__(
            max_length=40, required=True, strip=True,
            widget=forms.TextInput(attrs={"autocomplete": "nickname", "maxlength": 40}),
            help_text="What your partner will see. You can change it later.",
            **kwargs,
        )


# One box per consent, never bundled and never pre-ticked. Wording approved
# by the owner (2026-10-29); box 4 names Render and any configured email
# provider, matching the beta privacy notice.
CONSENT_BOX_KINDS = {
    "confirm_age": Consent.AGE,
    "agree_terms": Consent.TERMS,  # Now: read the beta privacy notice.
    "agree_sensitive": Consent.SENSITIVE,
    "agree_transfer": Consent.TRANSFER,
}


def consent_box_labels():
    provider = email_provider_name()
    transfer_details = (
        f"Render (web service and PostgreSQL database in Oregon, USA) and "
        f"{provider} (account email delivery)"
        if provider
        else "Render (web service and PostgreSQL database in Oregon, USA); account email delivery is disabled "
        "because no email provider is configured"
    )
    return {
        "confirm_age": "I confirm I'm 18 or older.",
        "agree_terms": mark_safe(
            "I've read the <a href=\"/privacy/#playing-safely\" target=\"_blank\">beta privacy notice "
            "and its safety rules</a> and understand Me &amp; You is a beta."
        ),
        "agree_sensitive": (
            "I consent to Me & You storing and processing the intimate and sensitive things I share "
            "(such as answers and messages about my relationship and sex life), only to run the app "
            "for me and my partner. Chat messages are encrypted when stored. Answers in Questions and "
            "Spicy Only aren't encrypted, but they're deleted as soon as either of you moves to the next "
            "question or resets the game. Custom questions are kept until your couple space is deleted, "
            "or until the person who wrote them deletes their account."
        ),
        "agree_transfer": (
            f"I consent to Me & You using {transfer_details}. If I turn on notifications, my browser's "
            "push service (such as Google, Apple or Mozilla) delivers them. "
            "Render may process my data outside Nigeria, where protections may differ from Nigerian law."
        ),
    }


def add_consent_boxes(form, kinds):
    """Add a required checkbox for each consent kind in `kinds`."""
    labels = consent_box_labels()
    for name, kind in CONSENT_BOX_KINDS.items():
        label = labels[name]
        if kind in kinds:
            form.fields[name] = forms.BooleanField(
                label=label, required=True,
                error_messages={"required": "Please tick this box to continue."},
            )


def consent_box_fields(form):
    return [form[name] for name in CONSENT_BOX_KINDS if name in form.fields]


def ticked_consents(form):
    return [kind for name, kind in CONSENT_BOX_KINDS.items() if form.cleaned_data.get(name)]


class ConsentForm(forms.Form):
    """Asks only for the consents this user hasn't given yet."""

    def __init__(self, *args, missing, **kwargs):
        super().__init__(*args, **kwargs)
        add_consent_boxes(self, missing)

    def consent_boxes(self):
        return consent_box_fields(self)


class RegistrationForm(BaseUserCreationForm):
    """Sign-up with email and password. Django's password validators run on
    password2 (length, common passwords, similarity to the email)."""

    display_name = DisplayNameField(label="Your name")
    # The account that already uses the submitted email, if any. The page
    # doesn't say so; the view emails that account's owner instead.
    existing_user = None

    class Meta:
        model = User
        fields = ("display_name", "email")
        widgets = {"email": forms.EmailInput(attrs={"autocomplete": "email"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_consent_boxes(self, list(CONSENT_BOX_KINDS.values()))

    def consent_boxes(self):
        return consent_box_fields(self)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        self.existing_user = User.objects.filter(email__iexact=email).first()
        if self.existing_user is not None:
            raise forms.ValidationError(
                "We couldn't create an account with these details. "
                "If you already have one, sign in or reset your password."
            )
        return email


class ProfileForm(forms.ModelForm):
    display_name = DisplayNameField(label="Your name")

    class Meta:
        model = User
        fields = ("display_name",)


class EmailAuthenticationForm(AuthenticationForm):
    """Django's sign-in form; its username field is the email address.
    Wrong email and wrong password give the same message."""

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget = forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True})

    def clean_username(self):
        return User.objects.normalize_email(self.cleaned_data.get("username"))

    # True when signing in cancelled a pending account deletion.
    restored = False

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError:
            # Django refuses inactive accounts. One deleted by its owner can
            # still sign in within 7 days, and that cancels the deletion.
            user = self._restorable_user()
            if user is None:
                raise
            from .deletion import cancel_deletion

            cancel_deletion(user)
            self.user_cache, self.restored = user, True
            return self.cleaned_data

    def _restorable_user(self):
        from .deletion import is_restorable

        email, password = self.cleaned_data.get("username"), self.cleaned_data.get("password")
        user = User.objects.filter(email__iexact=email).first() if email and password else None
        if user is None or not is_restorable(user) or not user.check_password(password):
            return None
        return user


class ResetRequestForm(PasswordResetForm):
    """Django's reset form (it only emails active users with a usable
    password, and saves the same way for unknown addresses). The link
    carries uid and token after "#", and is sent in the background."""

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email,
                  html_email_template_name=None):
        link = (f"{context['protocol']}://{context['domain']}/accounts/password/reset/confirm/"
                f"#{context['uid']}.{context['token']}")
        emails.send_in_background(context["user"], "password_reset", {"link": link})
