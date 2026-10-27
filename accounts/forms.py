from django import forms
from django.contrib.auth.forms import (
    AdminUserCreationForm,
    AuthenticationForm,
    BaseUserCreationForm,
    PasswordResetForm,
    UserChangeForm,
)

from . import emails

from .models import User


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


class RegistrationForm(BaseUserCreationForm):
    """Sign-up with email and password. Django's password validators run on
    password2 (length, common passwords, similarity to the email)."""

    display_name = DisplayNameField(label="Your name")

    class Meta:
        model = User
        fields = ("display_name", "email")
        widgets = {"email": forms.EmailInput(attrs={"autocomplete": "email"})}

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Sign in instead.")
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
