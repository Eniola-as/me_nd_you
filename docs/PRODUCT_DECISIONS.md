# Product decisions

Recorded decisions for Me & You. Each entry says what was decided, the
behaviour to build, and anything still open.

## 1. Legacy secret-word couples (decided; claim flow to build)

Preserve all existing secret-word couples and their data. Do not switch off
legacy access immediately. Retire it per couple only after both partners have
accounts, with a grace period.

Proposed transition (nothing is deleted at any step; every step is reversible
by an admin):

1. **Claim.** A signed-in member of a couple space enters the old couple's two
   names and secret word (checked like the legacy login, rate limited). The old
   couple is *linked* to the space: its custom questions appear in the space.
   No data is copied, moved or deleted. A legacy couple can be linked to one
   space only; a second claim is refused (an admin can unlink a wrong claim).
2. **Both partners on accounts.** Once the claiming space has two members, the
   legacy couple is marked "retiring" with a date (proposed: 14 days later).
   Until then the secret word keeps working, and the legacy pages show a notice
   asking the couple to sign in instead.
3. **Retired.** After the date, the secret word no longer opens that couple's
   legacy pages or room; the pages explain how to sign in. The legacy record,
   its custom questions and the link remain. An admin can clear the retirement.

Implications:
- Anyone who knows a couple's secret can claim it. That is the same access the
  secret already grants today; the grace period and admin unlink cover mistakes.
- Seen-question progress lives in each browser today, so it is not carried over.

Open: the grace period length (14 days proposed).

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
