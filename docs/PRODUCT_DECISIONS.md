# Product decisions

Recorded decisions for Me & You. Each entry says what was decided, the
behaviour to build, and anything still open.

## 1. Legacy secret-word couples (decided; built in couples/legacy.py)

Preserve all existing secret-word couples and their data. Do not switch off
legacy access immediately. Retire it per couple only after both partners have
accounts, with a 14-day grace period. Nothing is deleted at any step; every
step is reversible by an admin.

1. **Claim.** A signed-in member of a couple space enters the old couple's two
   names and secret word on the space page (rate limited, 5 a minute; wrong
   names and wrong secrets get the same answer). The old couple is *linked* to
   the space: its custom questions appear in the space. No data is copied,
   moved or deleted. A legacy couple links to one space, and a space links one
   legacy couple. The secret word keeps working.
2. **Ready.** Each member confirms "We've moved over" on the space page (and
   can take it back). The countdown starts only when the space has both
   members and both have confirmed: the secret word then keeps working for 14
   more days. Legacy pages show a notice explaining each stage, with the date.
3. **Deadline.** When the date passes (checked the next time the secret word
   or the space page is used), the secret word stops working only if the move
   is still complete: the space is open, both members are still in it and both
   are still confirmed. Otherwise the secret word keeps working and the link is
   flagged "needs resolution" for an admin. After retirement the legacy login,
   questions API, custom-question API and game room refuse the secret word,
   including connections that were already open.

Admin recovery (Django admin, Legacy links): *clear the retirement* (the
secret word works again; both confirm again to restart the countdown) and
*unlink* (undo the claim; the old couple works as before and can be claimed
again). Links can't be added or deleted by hand. A linked legacy couple is
never removed by `purge_inactive_sessions`.

Implications:
- Anyone who knows a couple's secret can claim it. That is the same access the
  secret already grants today; the readiness step, grace period and admin
  unlink cover mistakes.
- Seen-question progress lives in each browser today, so it is not carried over.

## 2. Display names (decided; build before public launch)

- Each account has a display name (1-40 characters, not unique), chosen at
  registration and changeable on an account page.
- Partners see each other's display name, never the email address. Login
  emails stay private to their owner (and admins).
- Existing accounts without a name are asked for one at their next sign-in;
  until then the partner sees a neutral placeholder ("Your partner"), never the
  email.

## 3. Leaving a couple (decided: safe, non-destructive; details proposed)

- Leaving needs an explicit confirmation step (a second screen that names the
  consequence), is a POST with CSRF protection, and is rate limited.
- Nothing is deleted. The couple, its custom questions and game history stay
  in the database.
- Proposed rule for what happens: when one member leaves, the couple is
  **closed** for both members. Both memberships end, pending invitations are
  revoked, live game rooms are closed, and each person can start or join a new
  couple. A closed couple's private content (custom questions, history) is
  never shown to a future partner of either person.
  - Why close it for both: a couple's custom questions can be intimate. If the
    remaining member could invite someone new into the same space, that new
    person would see them.
- Rejoining a closed couple is not offered at first; an admin can restore it.

Open: confirm the "closes for both" rule.
