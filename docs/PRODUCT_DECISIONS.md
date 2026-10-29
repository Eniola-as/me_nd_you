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

Update (2026-10-28): closed spaces are no longer kept forever. A closed
space, with everything in it, is permanently deleted 30 days after closing;
until then an admin can restore it and each member can download their data.
Both members get a neutral closure email and in-app notice (section 6).

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
- Later, not now: saved answer history. (Reactions to a revealed answer were
  added with chat, see §5; they are deleted with the answers.)

## 5. Private chat, presence and reactions (decided 2026-10-28)

- **Where:** a floating icon, bottom-right, on the play page, space page and
  mode menu. It opens a panel over the page (a full-width sheet on phones)
  with an unread badge. The icon must never cover game buttons, so on phones
  the page scrolls above a strip kept for it.
- **Who:** only the two members of the couple. Membership is checked on every
  message, and closing the couple or resetting a password cuts chat off at
  once.
- **History:** saved. The last 50 load first, then older on request. Each
  partner can delete their own messages for both of them (the row is
  removed), never the partner's.
- **When a couple closes:** messages are hidden from everyone, including the
  admin pages, and come back if an admin restores the couple. Pre-launch adds
  permanent deletion 30 days after closing.
- **Limits:** 1,000 characters per message; 30 messages per minute per person.
- **Unread badge:** a stored "last read" marker per member. The partner is
  never told (no read receipts).
- **Presence:** "Online", "Playing <mode>", "In your space", or "Last seen 5
  min ago", with one stored last-seen time per member. **Typing indicator:**
  yes, never stored.
- **Reactions:** WhatsApp-style. A quick row (❤️ 😂 😮 😢 🙏 👍 🔥) plus "+" for
  any single emoji, checked on the server. One per person per item,
  changeable or removable. On chat messages and on revealed Questions
  answers (deleted with the answers). Your own reaction shows at once and
  is undone if the server refuses it.
- **Encryption:** message text is encrypted at rest (Fernet), with keys from
  `CHAT_ENCRYPTION_KEYS`, never from the repo or `SECRET_KEY`. It is not
  end-to-end encryption. Reactions are not encrypted. Losing the key loses
  the messages (docs/DEPLOYMENT.md).
- **Out of scope for now:** images, voice notes, read receipts, editing,
  push notifications, search, link previews. Later: end-to-end encryption,
  an app lock, disappearing messages.

## 6. Pre-launch privacy (decided 2026-10-28)

- **Age:** a required "I confirm I'm 18 or older." box at sign-up; no birth
  date. Asked once.
- **Consents (NDPA 2023, GAID 2025):** separate, required, never pre-ticked
  boxes for the terms and privacy policy, intimate and sensitive content, and
  data stored and processed outside Nigeria. Each is stored with its time and
  `POLICY_VERSION`; a new version asks again. Existing accounts accept on
  their next request (pages redirect, the API answers 403, sockets refuse).
  Withdrawing consent means deleting the account; the profile lists consents
  with their dates and says so.
- **Policy pages:** `/privacy/` and `/terms/`, linked from every page;
  contact address from `PRIVACY_CONTACT_EMAIL`. The Outfit font is
  self-hosted, so no page contacts Google.
- **Download my data:** JSON with the account, consents, the couple's custom
  questions (marked yours where known: authors are recorded from this
  release), your own chat messages (decrypted) and reactions, never the
  partner's. Includes a closed space during its 30 days. Password required;
  3 an hour per account.
- **Account deletion:** password and a confirmation box. Closed at once
  (inactive, signed out everywhere, couple space closed for both), with a
  confirmation email giving the date. Signing in within 7 days cancels.
  After that, the account and everything the user wrote is permanently
  deleted, "usually within a day, and always within 30 days".
- **Closed spaces:** permanently deleted 30 days after closing. Both
  members get the approved neutral email and in-app notice: never who closed
  it, why, the partner's name or any content.
- **Purging:** no worker; at most hourly in the app, plus
  `purge_deleted_accounts` on every deploy.

## 7. Public-signup beta (decided 2026-10-29)

- **Scope:** a public-signup beta; the owner will share the URL with a small
  group of reviewers, but registration is not technically restricted. The
  polished Terms of Use and full legal review are deferred; the full
  privacy-policy draft and the terms stay unpublished. The 18+ gate, four
  required consents and privacy information stay. `/privacy/` is a short beta
  privacy notice that identifies unconfirmed facts without guessing.
- **Consent texts:** (1) 18 or older; (2) "I've read the beta privacy notice
  and understand Me & You is a beta."; (3) intimate content, saying exactly
  what is encrypted (chat) and what isn't (answers, custom questions) and how
  long each is kept; (4) data outside Nigeria, naming Render. Account email
  delivery is disabled until a provider is configured; any future provider
  must be disclosed before use and trigger renewed consent.
- **Email:** no provider is configured for the beta. Production refuses to
  send through the console/logs; verification, password recovery and email
  notices are unavailable. Public sign-up remains enabled, so users must keep
  their passwords safe.
- **Shared mode:** the couple has one mode, shown on every member page. The
  first mode starts at once; after that, either partner can request a switch,
  the other must accept, and nothing changes while it's pending. Declined
  keeps the mode. Every mode keeps its own progress; leaving a mode deletes
  its unrevealed answers and picks. Both partners are told in the app (no
  push notifications yet).
- **Turns:** Truth or Dare and Challenges are turn-based (unlimited skips);
  Spicy Only and Mixed are shared decks; Questions and Would You Rather keep
  simultaneous private answers and picks.
- **Would You Rather:** private picks, revealed together, never kept
  (Next, Reset and closing clear them).
- **Adding a prompt:** Truth or Dare asks Truth or Dare; other modes add to
  the current mode; Mixed asks for a real category (never "Mixed"). The server
  enforces this, and a prompt must belong to the couple's current mode.
- **New questions:** 1,038 of the owner's 1,040 imported as normal questions
  (397 and 398 left out as near-duplicates); the file stays so the comfort
  feature can mark them Sweet.
- **PWA:** installable; offline shows an offline page; nothing personal is
  cached on the device.
- **Deploy safety:** with `DEBUG` off, `check --deploy` errors on a draft
  policy version, unresolved placeholders in the published notice, or a
  missing privacy contact.
