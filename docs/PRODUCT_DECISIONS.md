# Product decisions

Recorded decisions for Me & You. Each entry says what was decided, the
behaviour to build, and anything still open.

## 1. Secret-word couples (removed 2026-10-27)

The original secret-word sessions had no real users: the only couples were
the owner's test data. Instead of moving them over to accounts, the whole
secret-word system was removed: the secret-word login and pages, its APIs and
WebSocket relay, the browser-driven game, and the claim and retirement flow
that had been built for the transition. Migration `game.0007` deletes any
secret-word couples with their custom questions and play history;
`couples.0004` drops the claim links. Everyone now plays with an account in a
couple space, on the server-held game engine.

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

## 4. Questions mode: private answers and a reveal (decided 2026-10-27)

Questions mode keeps its name and its questions (550 plus the couple's
custom questions) and adds optional private answers:

- Answering is optional. Next works at any time, so couples can still just
  talk.
- An answer is never sent to the partner's browser before both have
  answered; the server enforces this. Until then the partner only sees
  "<name> has answered."
- You can change your answer until the reveal. Answers are 1-500
  characters, checked by the server.
- If Next is pressed before both have answered, the lone answer is deleted
  unseen. If someone leaves or reloads, their answer waits on the server.
- Answers are not kept. Next, Reset and closing the couple delete them from
  the database; answer text is never written to the game history.
- Later, not now: saved answer history, and reactions to a revealed answer.
