# Me & You — Product Expansion Master Plan for Claude Code

## 1. Context and Objective

I have decided to expand my existing project, **Me & You**, by adding new multiplayer games and improving personalised experiences for two people.

**Repository:** `Eniola-as/me_nd_you`  
**Demo:** https://me-nd-you.onrender.com

You are working on an existing project, not a new application. The repository may contain completed features, partially completed features, uncommitted work, architectural documentation and recent changes that you must discover before doing anything.

Your first responsibility is to establish the actual current state of the project. Do not assume that historical plans, previous summaries or old implementation reports accurately describe the current codebase.

The objective is to extend what already exists, preserve working functionality and implement new features incrementally.

## 2. First: Establish the Actual Project State

Before implementing anything, inspect the repository thoroughly enough to understand its current architecture and progress.

### A. Git and project status

Inspect:

- Current branch and working directory status
- Recent commits and relevant commit history
- Uncommitted and untracked files
- Existing branches relevant to the work
- Current project documentation and implementation notes
- Any partially completed work related to games, rooms, invitations, personalisation or multiplayer synchronisation

Do not reset, discard, overwrite or clean up uncommitted changes. Do not assume that changes are disposable simply because they are not committed.

### B. Current application functionality

Inspect the actual code and determine the implementation status of:

- Registration and login
- User profiles and display names
- Invitations and private spaces
- Chat
- Existing game-selection interface
- Existing game modes
- Multiplayer game sessions and room management
- Server-authoritative game logic
- WebSocket event handling
- Turn management, timers and scoring
- Reconnection and session recovery
- Question and prompt storage
- Existing test infrastructure
- Deployment and database configuration

For each major feature, classify its status as:

1. Implemented and verified
2. Implemented but not adequately verified
3. Partially implemented
4. Planned but not implemented
5. Broken or blocked

Support these classifications with code references, relevant tests and observed results where available.

Do not infer that a feature works merely because its code exists. Do not claim a test passed unless you actually ran it and observed the result.

### C. Existing architectural decisions

Read the relevant documentation and inspect the implementation before proposing changes.

In particular, investigate any existing server-authoritative game engine, game-room state, event history, concurrency controls, idempotency, versioning, reconnect behaviour and legacy game protocols.

Reuse existing architecture wherever practical. Do not create a competing game engine or migrate every legacy game simply because a new game is being introduced.

### D. Report before implementation

Produce a concise but sufficiently detailed project-status report covering:

- Current architecture
- Completed and incomplete features
- Current game implementations
- Existing database models and relationships
- Existing multiplayer protocols
- Outstanding bugs or blockers relevant to this expansion
- Test coverage and available test commands
- Uncommitted work that must be preserved
- Recommended next steps

Then stop and wait for my approval before making significant changes.

You may perform the read-only inspection necessary to prepare this report. Do not push, deploy, modify production data or perform destructive operations.

---

## 3. Approved Product Direction

Me & You is a two-person interactive application that helps people connect through games, questions, challenges, shared memories and personalised experiences.

The product should be enjoyable, reliable, easy to use and meaningfully different from a generic collection of party games.

Proposed tagline:

**Me & You — Every connection has a story.**

### Supported relationship types

For now, support only:

1. Couples
2. Friends

Do not add sibling, parent-child, cousin or other relationship types in this expansion.

Both types should use shared game engines where possible, while the content and personalisation adapt to the type of space.

A user may eventually want separate spaces for a partner and a friend. Inspect the current architecture to determine whether multiple spaces per user are already supported.

Do not assume they are supported, and do not implement a new space system without reviewing the existing models, migration requirements and compatibility risks.

### Product principles

- Preserve working features.
- Prioritise correct behaviour and reliable multiplayer synchronisation over cosmetic redesign.
- Avoid unnecessary complexity.
- Keep the experience responsive on mobile and desktop.
- Use curated content and deterministic game rules where possible.
- Make personalisation optional.
- Protect private answers and sensitive information.
- Deliver complete, testable increments instead of large unfinished changes.

## 4. Existing Games to Preserve

The current product has six established game modes. Verify their current implementation and retain them:

1. Questions
2. Truth or Dare
3. Challenge Mode
4. Spicy Only
5. Mixed Mode
6. Would You Rather

Do not assume all six use the same game engine. Inspect each implementation before deciding how to integrate the new games.

Preserve existing behaviour unless a specific, justified change is needed.

### Content rules

Couples can receive general questions, relationship prompts, romantic content and optional adult content where appropriate.

Friends can receive general questions, friendship-specific prompts, shared-interest content and appropriate challenges.

Spicy Only must have suitable age and relationship eligibility restrictions enforced on the backend. Friends must not receive romantic or intimate content intended for Couples.

Do not rely on frontend visibility controls alone to enforce content restrictions.

## 5. New Games Approved for Expansion

The following five new games are approved. Build them in the sequence that best fits the existing architecture, dependencies and current project state. The sequence below is the default, not permission to skip the architecture review.

### Game 1: Emoji Decoder

Players solve emoji-based puzzles representing films, music, food, phrases, sports and other topics.

Examples:

- 🦁 + 👑 = The Lion King
- 🌧️ + 🐱 + 🐶 = Raining cats and dogs

Potential categories:

- Movies and television
- Music and songs
- Food
- Everyday expressions
- Sports
- Nigerian culture and slang
- General knowledge
- Couples
- Friendship
- Shared interests and memories

Required features:

- Alternating turns where appropriate
- Difficulty levels
- Hints
- Answer submission and validation
- Score tracking
- Skip and reveal options
- Clear round completion
- Rematch support
- Reconnection and state recovery
- Protection against duplicate scoring and submissions

Use deterministic answer validation with reasonable normalisation for case, punctuation, spacing and accepted alternative answers.

Do not expose secret answers to the other player before the reveal phase through API responses, rendered HTML, client state or WebSocket messages.

Use the existing game engine where appropriate. Keep the initial puzzle bank manageable and quality-reviewed.

### Game 2: Predict My Answer

A short-session prediction game distinct from Who Knows Who Best?

Example:

“If I suddenly received ₦10 million, what would I do first?”

Round flow:

1. Both players receive the same question.
2. Each privately submits their own answer.
3. Each predicts the other person's answer.
4. The server waits for the required submissions.
5. The answers and predictions are revealed.
6. The server calculates the scores using defined rules.

Potential categories:

- Money and lifestyle
- Food and entertainment
- Travel and adventure
- Habits and personality
- Hypothetical situations
- Friendship
- Relationships and future plans
- Funny choices
- Personal preferences

Prefer structured answer choices when they produce reliable scoring. If free-text answers are supported, document how matching works and avoid arbitrary scoring.

Private submissions must remain hidden until the correct reveal phase. Both clients must agree on the same question and round state.

### Game 3: Describe It Without Saying It

One player receives a secret word and describes it without using the word or designated forbidden words. The other player guesses.

Example:

Secret word: Football  
Forbidden words: Ball, goal, player

Required features:

- Secret word and forbidden-word list
- Alternating roles
- Timer
- Guess submission
- Scoring
- Skip and reveal
- Difficulty levels
- Category selection
- Round completion and replay

Possible categories include everyday objects, food, films, music, sports, hobbies, Nigerian culture, friendship, Couples and shared interests.

For the initial version, use written clues unless existing voice functionality supports the intended experience. Do not imply that built-in voice calling exists if it does not.

Validate important rules server-side. Document any limitations of the written-clue format.

### Game 4: Draw & Guess

One player receives a secret prompt and draws it on a canvas while the other player guesses.

Potential prompt categories:

- Fruits and food
- Animals
- Household objects
- Toys
- Brands and logos
- Films and recognisable characters, subject to appropriate asset and copyright considerations
- Hobbies and sports
- Gifts
- Restaurants and recognisable places
- Concrete objects associated with shared memories

Prompts should be drawable and recognisable. Avoid abstract prompts such as “draw your favourite date.” A concrete object, recognisable place or gift is more suitable.

Required features:

- Mouse and touchscreen drawing
- Pen, eraser, colour selection and clear canvas
- Timer
- Live drawing synchronisation
- Guess submission
- Alternating turns
- Score tracking
- Skip and reveal
- Difficulty levels
- Reconnection handling

Keep the secret prompt server-side until reveal. Use compact drawing-stroke events over the existing WebSocket infrastructure where practical, instead of repeatedly transferring full canvas images.

Do not turn private messages or sensitive answers into prompts without explicit user consent.

### Game 5: Guess the Act

One player acts out a prompt while the other guesses.

Possible categories:

- Animals
- Everyday activities
- Sports
- Hobbies
- General entertainment
- Couples
- Friendship

This game requires a way for players to see each other.

**Initial version:** Use an external video-calling application. Me & You should manage prompts, turns, timers and scores, but it will not provide built-in video calling in this expansion.

Display a clear explanation such as:

“Video calling is coming soon! For now, start a call with your preferred video-calling app, then return here to play.”

Do not imply that Me & You can access, record or transmit an external call.

Built-in video calling is a possible future feature, not part of the current scope.

## 6. Who Knows Who Best?

This is a separate planned game, not one of the five new games above. Preserve it in the roadmap and inspect whether any part of it already exists.

### Game structure

- 3 rounds
- 10 questions per round
- 30 questions per game
- Easy: 1 point
- Medium: 2 points
- Hard: 3 points
- Maximum: 60 points per player

Players answer questions about themselves privately and predict the other person's answers. The game reveals answers when the necessary submissions are complete and calculates scores.

Required features:

- Thirty questions per game
- Difficulty-based scoring
- Separate Couples and Friends content
- Categories
- Private answers before reveal
- Server-authoritative scoring
- Round summaries
- Final results
- Replay support
- Duplicate-scoring prevention
- Question history and repetition avoidance

### Question-bank target

The long-term goal is approximately 2,000 original, quality-reviewed questions:

- 1,000 Couples questions
- 1,000 Friends questions

For each bank:

- 350 easy
- 350 medium
- 300 hard

Do not generate and integrate all 2,000 questions in the first implementation phase.

First establish the game mechanics with a smaller, reviewed seed bank. Expand content in manageable batches after the game has been tested.

Store question attributes in a maintainable structure consistent with the existing project. Potential fields include relationship type, difficulty, category, answer type, point value and active status.

Avoid duplicates and near-duplicates. Track previously used questions per space or game history and prioritise unseen questions. Define sensible fallback behaviour when a bank is exhausted.

Both players must receive the same question, and the backend must determine scoring and reveal timing.

## 7. Personalisation

Personalisation should make the games feel relevant to each pair of players without creating a burdensome setup process.

Combine:

1. General questions and prompts
2. Relationship-specific content
3. User-selected interests
4. Shared interests
5. Optional shared memories
6. Optional inside jokes
7. Custom prompts explicitly submitted by users

Possible interests include:

- Films and television
- Music and artists
- Sports and teams
- Hobbies
- Food
- Travel
- Shared activities
- Inside jokes
- Memorable experiences

Users must be able to skip setup and start playing immediately.

Personalisation should be optional and consent-based. Do not scrape chat messages or automatically convert private answers into game prompts.

Do not send private user information to external AI services without explicit approval and a reviewed privacy design.

Begin with curated content and rule-based personalisation. Consider AI-generated prompts later, after evaluating privacy, quality, cost and safety.

If content ratios are useful, make them configurable. A starting hypothesis could be approximately 60% general, 25% interest-based and 15% relationship-specific content. Treat this as a testable default, not a fixed requirement.

## 8. Technical and Multiplayer Requirements

Inspect the current implementation before deciding how to implement each game.

For multiplayer features:

- The server controls canonical game state, turns, scores and round transitions.
- Secret answers remain hidden until reveal.
- Accepted actions are validated and authorised server-side.
- Duplicate requests are idempotent.
- Concurrent actions cannot produce conflicting state or duplicate scoring.
- State changes are persisted before relevant events are broadcast, where required by the existing architecture.
- Clients can reconnect and resynchronise.
- Invalid or stale actions return understandable errors.
- WebSocket messages are validated and authorised.
- Players cannot access spaces or rooms they do not belong to.
- Client-submitted scores and secret game state are never trusted.

Reuse the existing server-authoritative engine and documented patterns where appropriate. Do not build a competing architecture.

If some legacy games still use an older protocol, document the implications before migrating them. Do not silently migrate every legacy game while implementing a new one.

For timers, determine the authoritative server-side timing rules. Browser countdowns may display time, but must not independently determine scoring or round outcomes.

For Draw & Guess, use compact stroke events where feasible and handle message ordering and reconnection carefully.

## 9. Database, Security and Compatibility

Before making structural changes, inspect the actual data models, migrations and dependencies.

Pay particular attention to:

- Users and authentication
- Spaces and invitations
- Game rooms and sessions
- Questions and prompts
- Game events and state versions
- Existing data constraints
- Production and development database configuration

Do not assume multiple spaces per user are supported. If the current design restricts users to one space, report the constraint and explain possible solutions before proposing schema changes.

For any significant model or migration change, explain:

- Why it is necessary
- Which models and files will change
- Migration impact
- Compatibility risks
- Data preservation requirements
- Tests required

Do not delete or overwrite user data. Do not reset databases to make tests pass.

Do not expose secrets, credentials, private answers or sensitive data through logs, APIs, source control or WebSocket messages.

Do not push changes, deploy to Render, alter production environment variables, run production migrations or perform destructive Git operations without my explicit approval.

## 10. UI and UX

Preserve the existing visual identity and layout where practical.

Prioritise behaviour, data accuracy, speed and reliability over unnecessary redesign.

Requirements:

- Reuse existing templates, styles and components where possible.
- Keep the interface responsive on mobile and desktop.
- Support touch input for drawing.
- Clearly indicate turns, timers, scores and round progress.
- Show when a player is waiting for the other player.
- Provide feedback for accepted, rejected, skipped and revealed answers.
- Handle loading, empty, error and completed states.
- Make reconnecting and resuming understandable.
- Keep secret answers out of client-visible data until reveal.
- Maintain readable text and accessible controls.

Only propose substantial visual changes when existing UI patterns cannot support the feature adequately.

## 11. Implementation Strategy

After the initial audit, recommend an implementation sequence based on the actual state of the repository. The default order is below.

### Phase 0 — Current-state audit

Inspect and report before implementing. Preserve all existing work.

### Phase 1 — Emoji Decoder

Implement a small but complete version using existing architecture. Include puzzle content, validation, scoring, turns, reveal, reconnection, responsive UI and tests.

### Phase 2 — Predict My Answer

Implement private submissions, predictions, reveal and deterministic scoring.

### Phase 3 — Describe It Without Saying It

Implement secret prompts, forbidden words, guesses, turns, timers and scoring.

### Phase 4 — Draw & Guess

Implement canvas tools, stroke synchronisation, hidden prompts, turns, guesses, timers and scoring.

### Phase 5 — Guess the Act

Implement prompts, external-call guidance, turns, timers and scoring. Do not implement built-in video calling.

### Phase 6 — Who Knows Who Best?

Implement the complete thirty-question game, difficulty-based scoring, question history and separate Couples and Friends banks.

### Phase 7 — Personalisation

Introduce or improve optional interests, shared-topic prompts and curated personalisation after the core game mechanics work reliably.

### Phase 8 — Regression and compatibility

Verify all existing games, authentication, invitations, chat, room transitions and reconnection behaviour.

### Phase 9 — Final review

Document implementation, test results, known issues, security considerations and remaining work.

This sequence can be adjusted if the audit shows that another order is safer or more efficient. Explain any proposed deviation before implementing it.

## 12. Testing and Acceptance Criteria

Every phase must have its own completion criteria.

Test:

- Valid and invalid actions
- Room membership and authorisation
- Secret-answer protection
- Private submissions
- Correct and incorrect guesses
- Scoring and difficulty
- Skip and reveal
- Duplicate requests
- Concurrent actions
- Turn transitions
- Reconnection and state recovery
- Question repetition
- Relationship-specific content restrictions
- Desktop and mobile interactions
- Regression in existing games

Use the project's established test framework and commands. Run the relevant tests and report the actual results, including skipped tests, failures and environment limitations.

Use two or more independent browser sessions for multiplayer verification where browser automation is available.

Do not change legitimate application behaviour just to make tests pass.

A phase is not complete merely because the code has been written. It must meet its acceptance criteria, and remaining limitations must be documented.

## 13. Collaboration and Change Management

Follow these rules throughout the project:

1. Inspect before implementing.
2. Treat the repository as the source of truth for current progress.
3. Preserve uncommitted changes.
4. Reuse existing architecture and working code.
5. Work on one approved phase at a time.
6. Keep changes focused and reviewable.
7. Avoid unrelated refactoring.
8. Explain new dependencies and architectural changes.
9. Never invent test results.
10. Do not push, deploy or alter production data without explicit approval.
11. Do not add Build a Story.
12. Do not introduce new relationship types beyond Couples and Friends.
13. Do not implement built-in video calling in this expansion.
14. Do not generate all 2,000 questions before testing the game mechanics.
15. Document significant architectural decisions.

After each implementation phase, report:

- What changed
- Why the changes were necessary
- Files modified
- Models and migrations affected
- Tests actually run and their results
- Known bugs or limitations
- Security and compatibility considerations
- Whether the changes were committed
- Recommended next step

Do not proceed to another major phase until I have reviewed the report and approved it.

## 14. Immediate Instruction

**Begin with the read-only repository and progress audit. Do not start implementing the new games yet.**

Determine what is already complete, what remains incomplete and which architectural decisions have already been made.

Then return a concise, evidence-based report and a proposed next phase. If the audit identifies a critical issue that should be addressed before adding games, explain it rather than silently expanding the task.

Wait for my approval before making significant implementation changes.

The objective is to expand Me & You intelligently from its actual current state, protect existing functionality and deliver each new experience as a reliable multiplayer feature.
