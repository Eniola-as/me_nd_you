# Deploying Me & You on Render

This is the runbook for the PostgreSQL + Daphne setup in `render.yaml`.
Nothing here has been deployed yet. Items marked **Verify in Render** depend
on your Render account and plan and must be checked before relying on them.

## Architecture at launch

- **One always-on web instance running one Daphne process.** Daphne serves
  both HTTP and WebSockets (`me_nd_you.asgi:application`).
- **Managed PostgreSQL**, reached through `DATABASE_URL`. Without it the app
  falls back to a local SQLite file, which is for development only; the
  deploy check `game.W002` warns about that.
- **No Redis.** The channel layer and cache are in memory, inside the single
  Daphne process.

### What the single process means

Everything below holds only while there is exactly one Daphne process:

| Works with one process | Needs Redis (shared channel layer / cache) |
|---|---|
| WebSocket rooms (all sockets live in the one process) | More than one process or instance |
| Rate limits (counts kept in process memory) | Rate limits that hold across instances |
| Question cache | Presence and chat across instances |
| | Rooms surviving overlapping deploys |

During a deploy, sockets on the old process drop and pages reconnect to the
new one (the client retries with backoff). Rate-limit counts and cached
question lists reset on every restart.

## Environment variables

| Variable | Value | Where |
|---|---|---|
| `SECRET_KEY` | A new long random value. **The old key is in git history: rotate it.** | Dashboard only |
| `DEBUG` | `False` | `render.yaml` |
| `ALLOWED_HOSTS` | `me-nd-you.onrender.com` (plus any custom domain) | `render.yaml` |
| `PYTHON_VERSION` | `3.13.7` | `render.yaml` |
| `DATABASE_URL` | The database's **internal** connection string | Dashboard |
| `TRUSTED_PROXY_COUNT` | Number of proxies in front of the app. **Verify with Render; don't guess.** Until set, all visitors share one rate-limit bucket (`game.W001`). | Dashboard |
| `ADMIN_URL` | A hard-to-guess path ending in `/` | Dashboard |
| `EMAIL_PROVIDER` | `brevo`, `resend` or `postmark`. Mail goes through the provider's HTTPS API; there is no SMTP option (Render's free tier blocks SMTP). Unset, mail is only printed to the log (`accounts.W001`). | Dashboard |
| `EMAIL_API_KEY` | The provider's API key (Postmark: the server token) (`accounts.W002`) | Dashboard |
| `DEFAULT_FROM_EMAIL` | The sending address, e.g. `hello@your-domain`; it must be verified with the provider. Mail shows as from "Me & You" (`accounts.W003`). | Dashboard |
| `CHAT_ENCRYPTION_KEYS` | One or more Fernet keys, comma-separated; the first encrypts new messages, all can decrypt. **Required:** the app refuses to start in production without it. **Losing it loses every chat message** (see "Chat encryption key" below). | Dashboard only |
| `SECURE_HSTS_SECONDS` | Optional; default 3600. Raise once HTTPS is confirmed. | Dashboard |
| `RENDER_EXTERNAL_HOSTNAME` | Set by Render automatically | — |

`render.yaml` lists the dashboard-only variables with `sync: false`, so their
values never enter the repository.

## Before the first deploy

1. **Rotate `SECRET_KEY`** in the dashboard.
2. **Check whether the service is managed by this Blueprint.** If it was
   created by hand, Render ignores `render.yaml`, and the dashboard's build,
   start and pre-deploy commands are what actually run. Make them match
   `render.yaml`. (**Verify in Render.**)
3. **Choose plans** (cost decisions): an always-on web instance, and a
   managed PostgreSQL plan with backups. (**Verify in Render**: current
   prices, free-tier limits, whether `preDeployCommand` is available on the
   chosen instance type, and the database's backup schedule and retention.)
4. **Find out the proxy count** for `TRUSTED_PROXY_COUNT`.
5. **Choose an email provider** (Brevo, Resend or Postmark), create an API
   key and verify the sending address or domain with them. (**Verify with
   the provider**: free-tier sending limits and what verification needs.)
6. **Create the chat encryption key** on your own computer, put it in
   `CHAT_ENCRYPTION_KEYS` in the dashboard, and **store a copy outside
   Render** (a password manager) before the first chat message exists:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

## Chat encryption key

> **Warning: losing `CHAT_ENCRYPTION_KEYS` permanently loses every chat
> message.** There is no recovery: not by us, not by Render, not from a
> backup, because backups hold only the encrypted text. Render is not a backup
> of the key. Keep your own copy outside Render, for example in a password
> manager, and update it whenever the key changes.

- **What it protects:** a leaked database, dump or backup doesn't reveal any
  message text. **What it doesn't:** anyone with both the app's environment
  (the Render dashboard) and the database can read messages. It is not
  end-to-end encryption.
- **If a key leaks, or to rotate routinely:**
  1. Generate a new key (command above) and save it in your password manager.
  2. Set `CHAT_ENCRYPTION_KEYS` to `new,old` (the new key first) and deploy.
     New messages use the new key; old ones still decrypt with the old one.
  3. Run `python manage.py rotate_chat_keys` (Render Shell). It re-encrypts
     every message with the new key and reports any it couldn't read.
  4. Set `CHAT_ENCRYPTION_KEYS` to just `new` and deploy.
- **If the key is lost:** existing messages show "This message can't be
  shown". Set a new key so new messages work; the old ones can't be restored.

There is no production data to carry over: the secret-word couples were test
data and that system has been removed. The PostgreSQL database starts empty.

## First deploy

1. Create the PostgreSQL database and set `DATABASE_URL` to its internal
   connection string.
2. Set the other dashboard variables (table above).
3. Deploy. The build installs dependencies and collects static files; the
   pre-deploy step runs `migrate`, which on an empty database creates the
   accounts, couples, game, play and chat tables and loads the 2,067 questions
   (the original 1,917 plus 150 approved Truth or Dare dares).
4. Create an admin: `python manage.py createsuperuser` (email and password).
5. Run the checks below.

## After every deploy: checks

- `python manage.py check --deploy` shows no warnings (`game.W001`,
  `game.W002` and `accounts.W001`-`W003` must be gone).
- "Forgot your password?" on the sign-in page, for your own account: the
  email arrives, the link works, and other devices are signed out.
- The site loads over HTTPS, and `/admin/` is not the admin path.
- Two browsers on the same couple: Next on one shows the question on the
  other (WebSockets work).
- A new couple's first load in "Questions" mode shows 549 left: 550
  questions, with the first one on the card.
- In "Questions" mode, answer on one device: the other shows "<name> has
  answered." but not the answer, until it answers too.
- Chat: a message sent on one device arrives on the other with an unread
  badge, and presence shows where the partner is. If chat says "Chat isn't
  set up on this server yet", `CHAT_ENCRYPTION_KEYS` is missing.

## Backups

- Rely on the provider's automatic backups (**verify schedule and
  retention**), and **take a manual backup immediately before any deploy
  that changes the schema**:

  ```bash
  pg_dump --format=custom --no-owner "$DATABASE_URL" > backup-$(date +%Y%m%d-%H%M).dump
  ```

- Before launch, restore one backup into a throwaway database once
  (`pg_restore --no-owner -d <throwaway url> backup.dump`) to prove the
  backups work.

## Rollback

- **Code:** redeploy the previous commit (Render's rollback, **verify on the
  plan**). This is only safe if the newer migrations added things rather
  than removed them, so write migrations in two steps: add new columns or
  tables first, remove old ones in a later release.
- **Data:** restore the manual backup taken before the deploy. Anything
  written after that backup is lost, so take it right before deploying.

## Migration history notes

- `game/migrations/0001_squashed_0005_repair_questions.py` replaces
  `0001`-`0005`. Fresh databases (and PostgreSQL in particular) use only the
  squash; the original `0003` cannot run on PostgreSQL.
- Keep the original `0001`-`0005` files until no database is part-way
  through them (for example a local database still at `0003`).
- Databases created before `accounts.User` cannot be migrated in place;
  carry their game data over as described in the README.
