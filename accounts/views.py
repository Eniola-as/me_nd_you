from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, PasswordResetDoneView, PasswordResetView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from game.views import ClientRateThrottle

from . import emails
from .forms import EmailAuthenticationForm, ProfileForm, RegistrationForm, ResetRequestForm
from .sessions import sign_out_everywhere

# Session flag: the verification banner was dismissed. Signing in starts a
# new session, so it comes back on the next sign-in.
BANNER_DISMISSED = "verify_banner_dismissed"


def rate_limited(scope):
    """Limit POSTs to a view per client address (rates in settings), using
    the same throttle as the API. Counts are per process (in-memory cache)."""

    throttle_class = type(f"{scope.title()}Throttle", (ClientRateThrottle,), {"scope": scope})

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method == "POST" and not throttle_class().allow_request(request, None):
                return HttpResponse(
                    "Too many attempts. Please wait a minute and try again.", status=429
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _next_url(request, default="/space/"):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return default


@rate_limited("account_register")
@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("/space/")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)  # Starts a fresh session (new session key).
        emails.send_verification_email(request, user)  # A failure doesn't stop sign-up.
        return redirect(_next_url(request))
    return render(request, "accounts/register.html", {"form": form, "next": _next_url(request)})


@login_required
@rate_limited("account_profile")
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your name is updated.")
        return redirect("/space/")
    return render(request, "accounts/profile.html", {"form": form})


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


sign_in = rate_limited("account_login")(EmailLoginView.as_view())


@ensure_csrf_cookie
@rate_limited("account_verify_email")
@require_http_methods(["GET", "POST"])
def verify_email(request):
    """Verification links look like /accounts/verify/#<token>. Browsers never
    send the part after "#"; this page reads it and posts it back. Works
    without signing in, and doesn't sign anyone in."""
    if request.method == "GET":
        return render(request, "accounts/verify_email.html", {"state": "pending"})
    user = emails.user_for_verification_token(request.POST.get("token", ""))
    if user is not None:
        emails.mark_verified(user)
    return render(request, "accounts/verify_email.html", {"state": "verified" if user else "invalid"})


RESEND_MESSAGES = {
    emails.SENT: (messages.SUCCESS, "We've sent a new link to {email}. It works for 3 days."),
    emails.COOLDOWN: (messages.INFO, "We just sent you a link. Check your inbox, or try again in a couple of minutes."),
    emails.ALREADY_VERIFIED: (messages.INFO, "Your email is already verified."),
    emails.FAILED: (messages.ERROR, "We couldn't send the email just now. Please try again later."),
}


@login_required
@rate_limited("account_verify_email")
@require_POST
def resend_verification(request):
    level, text = RESEND_MESSAGES[emails.send_verification_email(request, request.user)]
    messages.add_message(request, level, text.format(email=request.user.email))
    return redirect(_next_url(request))


@login_required
@require_POST
def dismiss_verification_banner(request):
    request.session[BANNER_DISMISSED] = True
    return redirect(_next_url(request))


password_reset = rate_limited("account_password_reset")(PasswordResetView.as_view(
    form_class=ResetRequestForm,
    template_name="accounts/password_reset.html",
    success_url="/accounts/password/reset/sent/",
))

password_reset_sent = PasswordResetDoneView.as_view(template_name="accounts/password_reset_sent.html")

# Session key holding "<uid>.<token>" between opening the link and choosing
# the new password, so the token isn't put back into the page.
RESET_TOKEN = "password_reset_token"


def _user_for_reset_token(token):
    """The user a valid "<uid>.<token>" reset token belongs to, or None.
    Django's tokens expire after PASSWORD_RESET_TIMEOUT and stop working
    once the password (or last sign-in) changes."""
    if not token or len(token) > 200:
        return None
    uidb64, _, key = token.partition(".")
    User = get_user_model()
    try:
        user = User.objects.get(pk=urlsafe_base64_decode(uidb64).decode())
    except (ValueError, TypeError, OverflowError, ValidationError, User.DoesNotExist):
        return None
    return user if default_token_generator.check_token(user, key) else None


@ensure_csrf_cookie
@rate_limited("account_password_reset")
@require_http_methods(["GET", "POST"])
def password_reset_confirm(request):
    """Reset links look like /accounts/password/reset/confirm/#<uid>.<token>.
    This page reads the part after "#" and posts it; a valid token is kept
    in the session while the new password is chosen."""
    template = "accounts/password_reset_confirm.html"
    if request.method == "GET":
        return render(request, template, {"state": "pending"})
    if "token" in request.POST:
        token = request.POST["token"]
        user = _user_for_reset_token(token)
        if user is None:
            return render(request, template, {"state": "invalid"})
        request.session[RESET_TOKEN] = token
        return render(request, template, {"state": "choose", "form": SetPasswordForm(user)})

    user = _user_for_reset_token(request.session.get(RESET_TOKEN))
    if user is None:
        return render(request, template, {"state": "invalid"})
    form = SetPasswordForm(user, request.POST)
    if not form.is_valid():
        return render(request, template, {"state": "choose", "form": form})
    with transaction.atomic():
        form.save()
        emails.mark_verified(user)  # The link proved they read this inbox.
        logout(request)  # This browser too; also drops the stored token.
        sign_out_everywhere(user)
    messages.success(request, "Your password is changed. Sign in with your new password.")
    return redirect("/accounts/login/")
