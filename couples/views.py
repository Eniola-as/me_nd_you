import logging
import re

from django.contrib import messages
from django.db import DatabaseError
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from accounts.views import rate_limited
from notifications import services as notifications
from play import modes

from . import services
from .notices import closure_notice_for, send_closure_notices

logger = logging.getLogger(__name__)

# The token from an invitation link waits here until the person accepts. It
# never goes back into a URL or a page.
PENDING_INVITE = "pending_invite"
NEW_INVITE_URL = "new_invite_url"


# Real tokens are 43 characters; anything far longer is not kept.
MAX_TOKEN_LENGTH = 100
TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{20,%d}" % MAX_TOKEN_LENGTH)


def token_from_link(text):
    """The token from a pasted invitation link (".../invite/#<token>") or a
    pasted bare token; None if it can't be one."""
    text = (text or "").strip()
    if "#" in text:
        text = text.split("#", 1)[1].strip()
    return text if TOKEN_SHAPE.fullmatch(text) else None


@ensure_csrf_cookie
@rate_limited("invite_link")
@require_http_methods(["GET", "POST"])
def invitation_page(request):
    """Invitation links look like /invite/#<token>. Browsers never send the
    part after "#", so the token stays out of server and proxy logs; this
    page reads it and posts it back."""
    if request.method == "GET":
        return render(request, "couples/invite.html")
    if "link" in request.POST:
        # Pasted on this page (e.g. from "Have an invite?" on sign-in).
        token = token_from_link(request.POST["link"])
        if token is None:
            messages.error(request, services.InvalidInvitation.message)
            return redirect("/invite/")
    else:
        token = request.POST.get("token", "")
    if token and len(token) <= MAX_TOKEN_LENGTH:
        request.session[PENDING_INVITE] = token
    if not request.user.is_authenticated:
        return redirect("/accounts/login/?next=/space/")
    return redirect("/space/")


@login_required
@rate_limited("space_action")
@require_http_methods(["GET", "POST"])
def space(request):
    if request.method == "POST":
        _handle_action(request)
        return redirect("/space/")

    user = request.user
    membership = services.active_membership(user)
    return render(request, "couples/space.html", {
        "membership": membership,
        "partner": services.partner_of(user),
        "pending_invitation": services.pending_invitation(user),
        # Shown once, right after it was created.
        "new_invite_url": request.session.pop(NEW_INVITE_URL, None),
        "invite": _pending_invite(request),
        # (The unread count comes from notifications.context_processors.)
        "notification_items": notifications.recent(user) if membership else [],
        "closure_notice": closure_notice_for(user),
        **modes.page_context(user),
    })


def _pending_invite(request):
    """What the waiting invitation would do, checked afresh on every view:
    {"state": JOIN | ALREADY_MEMBER | SWITCH, "inviter": name}, or
    {"error": message} once (the dead invitation is then forgotten)."""
    token = request.session.get(PENDING_INVITE)
    if not token:
        return None
    try:
        state, inviter = services.invitation_for(request.user, token)
    except services.InvitationError as error:
        request.session.pop(PENDING_INVITE, None)
        return {"error": str(error)}
    return {"state": state, "inviter": inviter}


def _accept_invite(request):
    user = request.user
    token = request.session.get(PENDING_INVITE)
    if not token:
        messages.error(request, "Open the invitation link again to join.")
        return
    previous = services.active_couple(user)
    try:
        services.redeem_invitation(user, token, switch=request.POST.get("confirm_switch") == "yes")
    except services.SwitchNeedsConfirmation as error:
        messages.error(request, str(error))  # The invitation stays, ready to confirm.
        return
    except services.AlreadyMember as error:
        request.session.pop(PENDING_INVITE, None)
        messages.info(request, str(error))
        return
    except services.InvitationError:
        request.session.pop(PENDING_INVITE, None)
        raise
    except DatabaseError:
        logger.exception("Accepting an invitation failed.")
        messages.error(request, "Something went wrong while joining. Nothing has changed: "
                                "you're still in the same space as before. Please try again.")
        return
    request.session.pop(PENDING_INVITE, None)
    if previous is not None:
        previous.refresh_from_db()
        send_closure_notices(request, previous)
        messages.success(request, "Your previous space is closed, and you've joined your partner's couple space.")
    else:
        messages.success(request, "You've joined your partner's couple space.")


def _handle_action(request):
    user, action = request.user, request.POST.get("action")
    try:
        if action == "create_couple":
            services.create_couple(user)
            messages.success(request, "Your couple space is ready. Invite your partner.")
        elif action == "create_invite":
            token = services.create_invitation(user)
            request.session[NEW_INVITE_URL] = request.build_absolute_uri(f"/invite/#{token}")
        elif action == "revoke_invites":
            services.revoke_invitations(user)
            messages.success(request, "The invitation link no longer works.")
        elif action == "accept_invite":
            _accept_invite(request)
        elif action == "use_invite_link":
            token = token_from_link(request.POST.get("invite_link"))
            if token is None:
                messages.error(request, services.InvalidInvitation.message)
            else:
                request.session[PENDING_INVITE] = token
        elif action == "dismiss_invite":
            request.session.pop(PENDING_INVITE, None)
        elif action == "leave_couple":
            if request.POST.get("confirm") != "yes":
                messages.error(request, "Tick the box to confirm that you want to close this space.")
            else:
                couple = services.close_couple(user)
                send_closure_notices(request, couple)
                messages.success(request, "You left. The couple space is closed for both of you.")
    except services.InvitationError as error:
        messages.error(request, str(error))
