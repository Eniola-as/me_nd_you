# Multiplayer research and game-engine design

> Update 2026-10-27: the secret-word system has been removed (see
> docs/PRODUCT_DECISIONS.md §1). Every mode now runs on this engine; the
> mentions of legacy secret-word rooms below describe the state at the time.

## Part 1: Research (publicly observable mechanics)

Only behaviour visible to players or described publicly. No code, assets,
names or designs are taken from these games. "Observed" means stated by the
official site or listing; "reported" means third-party guides (which disagree
on defaults); "assumption" means my inference.

### Gartic Phone (telephone drawing game)
- Observed: a host creates a room and shares a link; the host starts the game
  ([Google Play listing](https://play.google.com/store/apps/details?id=com.gartic.garticphone&hl=en),
  [Gartic guide](https://medium.com/gartic/the-ultimate-gartic-phone-guide-all-modes-explained-805404f94948)).
- Observed: "Everyone writes a starting sentence", then players alternate
  drawing and describing; at the end everyone flips through the albums
  (Google Play listing). Every player acts in the *same phase at the same
  time*, and the reveal is a separate phase.
- Reported: the host sets timing (normal, fast, slow, progressive, regressive,
  infinite, or "host's decision"), turns and secrecy
  ([TheGamer](https://www.thegamer.com/gartic-phone-all-game-modes-ranked/),
  [Gamer Tweak](https://gamertweak.com/how-to-play-gartic-phone/)).
- Assumption: a phase ends when everyone submits or the timer expires, which
  needs the server to know who has submitted.

### skribbl.io (drawing and guessing)
- Observed on [skribbl.io](https://skribbl.io/): private rooms with a copyable
  invite link; settings for players (2-20), draw time, rounds (2-10), word
  count (1-5 choices), hints (0-5), custom words; turns where one player
  draws a chosen word and others guess for points.
- Reported: a turn ends when time runs out or everyone has guessed; hints
  reveal letters over time
  ([iogameguide](https://iogameguide.com/guides/skribbl-io-guide)).
- Observed (unofficial protocol docs,
  [scribble-rs/skribbl.io-docs](https://github.com/scribble-rs/skribbl.io-docs/wiki)):
  Socket.IO events are mostly *server-to-client* announcements such as
  "Update lobby state", "Update drawer", "Update lobby time",
  "Player has been connected/disconnected", "Reveal word". Clients send
  intents ("Choose word", "Draw", "Send chat message", "Start game").
  Takeaway: the server decides the phase, the drawer and the clock; clients
  send intents and render what the server announces.

### Couples' question games
- We're Not Really Strangers: three levels that move from light to deeper
  prompts, a minimum number of cards per level before moving on, "wild cards"
  that change what everyone does, and a final card
  ([Wikipedia](https://en.wikipedia.org/wiki/We're_Not_Really_Strangers),
  [Daily Free Press](https://dailyfreepress.com/2023/02/21/we-really-are-not-strangers/)).
  No skip rule was found.
- Paired: each partner answers the same question privately; neither answer is
  shown until both have answered ("answer then reveal")
  ([review](https://feelclose.app/blog/paired-couples-app-review),
  [WhistleOut](https://www.whistleout.com/CellPhones/Apps/paired-app-couples-relationship-questions)).

### What this means for Me & You
1. **The server owns the game.** It decides the current card, phase and turn.
   Clients send intents and render server snapshots.
2. **Phases.** A game is a sequence of phases (choose, answer, reveal, next).
   Some phases are simultaneous (both partners answer), some turn-based.
3. **Hidden until both act.** "Answer then reveal" fits couples well and
   needs the server to hide a partner's answer until both have answered.
4. **Comfort and pacing.** Intensity levels, a session length (number of
   cards), a skip that costs nothing, and gradual progression from light to
   deep.
5. **Room and rejoin.** Invite link, host or either partner starts; a
   reconnecting player gets the current state at once.

## Part 2: Audit of the current game flow (verified in the code)

| What | Where it lives today | Authoritative? |
|---|---|---|
| Question bank and custom questions | PostgreSQL / SQLite (`Question`, `CustomQuestion`) | Yes |
| Who may play (session, membership) | Server | Yes |
| Deck order (seed) | Each browser: URL `seed`, `localStorage` (`play.html` 299-408; new seed per mode click, `mode_select.html` 157) | **No** |
| Current card | Each browser's `currentQuestionText` (`play.html` 306) | **No** |
| Seen questions | Each browser's `localStorage` (`play.html` 366-386) | **No** |
| Next question choice | Each browser takes the next card from its own deck (`play.html` 426-433) | **No** |
| Reset | Each browser clears its own progress; a reset message asks the partner to do the same (`play.html` 454) | **No** |
| Reconnect | Peer-to-peer `sync_request`/`sync_response` between pages | **No** |
| Played-question history | `PlayedQuestion` table exists but nothing reads or writes it | Unused |
| WebSocket server | Validates and relays messages; stores nothing (`consumers.py`) | Relay only |

Weaknesses verified:
1. **Simultaneous Next diverges.** Two browsers (seeds 7 and 8) pressed Next
   at the same moment: A showed "What's your favorite thing to do with
   friends?", B showed "What's a compliment you love giving?". Their seen
   counts (2 and 1) and remaining counts (548 and 549) also differ.
2. **Different decks.** Each mode click creates a new seed, so partners
   shuffle different decks; the URL seed overrides any seed from a reset or
   sync.
3. **Repeats.** A card shown because the partner pressed Next is not marked
   seen locally, so it can come up again.
4. **State lost or wrong on devices.** Progress is per browser; a new device
   or cleared storage starts over; two tabs of one browser share progress.
5. **Reconnect depends on the partner being online**, and two pages that
   reconnect at once while out of sync can swap cards.
6. **No server record of what was played.**

The smoke tests pass because they check relaying and the sync heuristics, not
that both partners share one authoritative sequence of cards.

## Part 3: Design (original)

### Scope
Couple spaces first. Legacy secret-word rooms keep today's relay protocol
unchanged until they are retired (see PRODUCT_DECISIONS.md), so nothing
breaks for them.

### Data model (new `play` app)
- `GameRoom`: one per couple space and game type that is in progress.
  - `id` (UUID), `couple` (FK), `game` (registered game type, e.g.
    `questions`), `settings` (JSON: mode, intensity, length), `state` (JSON,
    owned by the game type), `version` (integer, +1 per change),
    `status` (`active` / `finished`), timestamps.
  - Unique: one active room per (couple, game).
- `RoomEvent`: append-only history. `room`, `version`, `kind`, `actor`
  (user), `payload` (JSON), `request_id` (UUID from the client), time.
  - Unique (room, version): two writers can't record the same step.
  - Unique (room, request_id): a retried request is applied once.
  - Replaces the unused `PlayedQuestion` for spaces (that table is kept).

### Game types (pure Python, no I/O)
Each game type implements:
- `start(settings, cards) -> state`
- `allowed(state, actor_slot) -> set of actions`
- `apply(state, action, actor_slot, payload) -> (new_state, events)` or a
  validation error
- `view(state, viewer_slot) -> public state` (hides what this viewer must not
  see yet, e.g. a partner's unrevealed answer)

The first type, `questions`, covers today's modes (Questions, Truth or Dare,
Spicy, Challenge, Mixed, Would You Rather as plain prompts):
- `state`: `deck` (ordered list of card ids, fixed at start), `position`,
  `current` (card text, mode, custom flag), `seed`.
- Actions: `next`, `reset` (new shuffled deck), later `skip` (no penalty).
- Custom questions added mid-game are inserted at a random later position
  of the remaining deck, so both partners get them, once.

Later types plug into the same engine: "answer then reveal" (simultaneous
answers, hidden until both submit), turn-based Truth or Dare (whose turn is
part of `state`), quizzes about each other, guessing games, and drawing games
(strokes are relayed live over the socket without database writes; only
the finished drawing is saved when the phase ends).

### Event protocol (WebSocket `/ws/space/<game>/`)
- On connect (after membership is checked): server sends
  `{"type": "state", "version": n, "state": {...view...}}`.
- Client action:
  `{"type": "action", "action": "next", "expectedVersion": n, "requestId": "<uuid>"}`
- After each committed change, the server sends every connected member the
  new `state` with its `version`.
- Rejections go to the sender only:
  - `{"type": "error", "reason": "stale", "requestId": ...}` followed by the
    current `state` (someone else acted first);
  - `forbidden` (not an active member now), `invalid` (bad action or input).
- Clients never decide what comes next; they render the latest version and
  ignore anything older.

### Transactions and concurrency
One action = one database transaction:
1. Lock the room row (`select_for_update`; PostgreSQL).
2. Re-check the actor's active membership in the room's couple (every
   action, not just on connect).
3. If `request_id` already recorded, return the recorded result (idempotent
   retry).
4. If `expectedVersion != version`, reject as `stale`.
5. Apply the game type, write the new `state` with `version + 1`, insert the
   `RoomEvent` (the unique (room, version) constraint backs up the lock on
   SQLite, where the row lock is a no-op).
6. Commit, then broadcast (`transaction.on_commit`), so nobody sees a state
   that was rolled back.

Simultaneous Next: both send `expectedVersion n`; the first commits `n+1`,
the second is rejected as stale and receives `n+1`. Exactly one advance, no
skipped card, both show the same card.

### Reconnects and refreshes
The server holds the state, so a refresh or reconnect simply receives the
current snapshot. Offline actions carry the version they were based on and
are rejected as stale if the game moved on, never applied twice (request id).
The peer-to-peer sync messages become unnecessary for spaces.

### Infrastructure
No new services. PostgreSQL holds the state; the existing in-memory channel
layer broadcasts within the one Daphne process. Timed phases (later) use
"lazy deadlines": the deadline is stored in `state` and enforced whenever the
room is next read or acted on, so no background worker is needed at launch.

### Tests
- Game type: pure transition tests (deck order, next at end of deck, reset,
  custom insertion, hidden views).
- Service: version conflicts, idempotent retries, membership re-checked per
  action, a member who left is refused, legacy rooms untouched.
- PostgreSQL concurrency: two threads send `next` at version n; exactly one
  advance and the stored deck position moves by one.
- WebSocket: snapshot on connect, both members receive the same version,
  stale and forbidden replies.
- Browser: the simultaneous-Next demonstration from Part 2 becomes a
  regression test (both browsers must show the same card).

### Implementation checkpoints
1. `play` app: `GameRoom`, `RoomEvent`, the `questions` game type, and the
   action service with versioning, idempotency and membership checks
   (PostgreSQL concurrency tests).
2. Space WebSocket protocol v2: snapshot on connect, actions, broadcast.
3. `play.html` space mode renders server state (reuses `card.js`, the card
   and buttons); legacy mode unchanged.
4. Then the product decisions: display names, leaving a couple, the legacy
   claim flow.
