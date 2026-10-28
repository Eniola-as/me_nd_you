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


# One box per consent, never bundled and never pre-ticked. Wording is a
# draft for the owner's review.
CONSENT_BOXES = {
    "confirm_age": (Consent.AGE, "I confirm I'm 18 or older."),
    "agree_terms": (Consent.TERMS, mark_safe(
        'I agree to the <a href="/terms/" target="_blank">Terms of Use</a> and the '
        '<a href="/privacy/" target="_blank">Privacy Policy</a>.'
    )),
    "agree_sensitive": (Consent.SENSITIVE, (
        "I consent to Me & You storing and processing the intimate and sensitive things I share "
        "(such as answers and messages about my relationship and sex life), only to run the app "
        "for me and my partner."
    )),
    "agree_transfer": (Consent.TRANSFER, (
        "I consent to my data being stored and processed outside Nigeria by Me & You's hosting "
        "and email providers, where it may not be protected to the same standard as Nigerian law."
    )),
}


def add_consent_boxes(form, kinds):
    """Add a required checkbox for each consent kind in `kinds`."""
    for name, (kind, label) in CONSENT_BOXES.items():
        if kind in kinds:
            form.fields[name] = forms.BooleanField(
                label=label, required=True,
                error_messages={"required": "Please tick this box to continue."},
            )


def consent_box_fields(form):
    return [form[name] for name in CONSENT_BOXES if name in form.fields]


def ticked_consents(form):
    return [kind for name, (kind, _) in CONSENT_BOXES.items() if form.cleaned_data.get(name)]


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
        add_consent_boxes(self, [kind for kind, _ in CONSENT_BOXES.values()])

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


class ResetRequestForm(PasswordResetForm):
    """Django's reset form (it only emails active users with a usable
    password, and saves the same way for unknown addresses). The link
    carries uid and token after "#", and is sent in the background."""

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email,
                  html_email_template_name=None):
        link = (f"{context['protocol']}://{context['domain']}/accounts/password/reset/confirm/"
                f"#{context['uid']}.{context['token']}")
        emails.send_in_background(context["user"], "password_reset", {"link": link})
