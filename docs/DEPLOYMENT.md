# Deploying Me & You on Render

This is the runbook for the PostgreSQL + Daphne setup in `render.yaml`.
Render uses a manually created web service, so dashboard commands—not
`render.yaml`—control its active build and start commands.

## Architecture at launch

- **One web instance running one Daphne process.** Daphne serves both HTTP and
  WebSockets (`me_nd_you.asgi:application`). On Render's free web plan, the
  service sleeps after 15 minutes without inbound traffic; its next request
  can take about a minute, and sleeping/restarts can drop WebSocket sessions.
- **Managed PostgreSQL**, reached through `DATABASE_URL`. Without it the app
  falls back to a local SQLite file, which is for development only; the
  deploy check `game.W002` warns about that.
- **No Redis.** The channel layer and cache are in memory, inside the single
  Daphne process.

### Free-plan deploy commands

Render's Free web service does not provide a pre-deploy command. Run database
migrations in the build command instead. This means the current database is
changed during the build while the previous app version may still be serving;
take a database backup before deploying whenever the data must be retained.
The Free PostgreSQL database has no backups and expires after 30 days, so do
not treat beta data as durable. Account and couple retention cleanup also runs
hourly in the app.

## Current Hobby workspace limits

The Render dashboard currently identifies Hobby as the workspace's $0/month
plan, **plus compute costs for paid service plans**. It lists 5 GB of
bandwidth ($0.15/GB after), 500 build minutes, two custom domains
($0.25/domain after), unlimited projects with two environments, and up to 25
services. Monitor bandwidth and do not select a paid compute size unless
intended. The workspace currently shows 14-day log retention and retention of
15 builds. These limits can change; confirm them in the dashboard before
relying on them.

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
| `EMAIL_PROVIDER` | Optional: `brevo`, `resend` or `postmark`. Mail goes through the provider's HTTPS API; there is no SMTP option. Without a provider, outbound email is safely disabled (`accounts.W001`); no email contents are written to logs. | Dashboard |
| `EMAIL_API_KEY` | The provider's API key (Postmark: the server token) (`accounts.W002` if a provider is selected). | Dashboard |
| `DEFAULT_FROM_EMAIL` | The sending address, e.g. `hello@your-domain`; it must be verified with the provider (`accounts.W003` if a provider is selected). | Dashboard |
| `CHAT_ENCRYPTION_KEYS` | One or more Fernet keys, comma-separated; the first encrypts new messages, all can decrypt. **Required:** the app refuses to start in production without it. **Losing it loses every chat message** (see "Chat encryption key" below). | Dashboard only |
| `PRIVACY_CONTACT_EMAIL` | `meandyouonlineandenquiry@gmail.com` (the owner's privacy contact). The address that answers privacy requests; shown on `/privacy/`, `/terms/` and in account emails (`accounts.W004`). | Dashboard |
| `SECURE_HSTS_SECONDS` | Optional; default 3600. Raise once HTTPS is confirmed. | Dashboard |
| `RENDER_EXTERNAL_HOSTNAME` | Set by Render automatically | — |

`render.yaml` lists the dashboard-only variables with `sync: false`, so their
values never enter the repository.

## Deployment checklist

1. **Rotate `SECRET_KEY`** in the dashboard.
2. **Keep the dashboard commands aligned with `render.yaml`.** The manually
   created service uses `pip install -r requirements.txt && python manage.py
   collectstatic --noinput && python manage.py migrate --noinput` as its build
   command and `daphne -b 0.0.0.0 -p $PORT me_nd_you.asgi:application` as its
   start command. Do not configure a pre-deploy command on the Free plan.
3. **Confirm the plan and region before relying on resources.** The current
   web service uses Render's Free instance; the PostgreSQL database was
   created on the Free plan in Oregon. It is limited to 1 GB, expires 30 days
   after creation, has a 14-day upgrade grace period, and has no backups;
   after the grace period it is deleted. Do not treat it as durable storage.
   Use a paid database with backups if beta data must be retained.
4. **Find out the proxy count** for `TRUSTED_PROXY_COUNT`.
5. **Email is deferred for this beta.** Leave `EMAIL_PROVIDER`,
   `EMAIL_API_KEY` and `DEFAULT_FROM_EMAIL` unset. Production then refuses to
   send email through the console or logs. Email verification, password
   recovery and account/closure email notices are unavailable; users must
   keep their passwords safe. `accounts.W001` is expected in `check --deploy`.
   Before enabling a provider later, verify delivery and its processing terms,
   update the privacy/consent text and bump `POLICY_VERSION`.
6. **Create the chat encryption key** on your own computer, put it in
   `CHAT_ENCRYPTION_KEYS` in the dashboard, and **store a copy outside
   Render** (a password manager) before the first chat message exists:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
7. **Review `/privacy/` before deployment.** The notice distinguishes
   confirmed facts from unverified ones; do not replace unknowns with guesses.
   Update it if provider facts change. `check --deploy` refuses while `[CHECK]` or
   `[DEPENDS ON]` placeholders remain (`accounts.E002`/`E003`), while
   `POLICY_VERSION` contains "draft" (`accounts.E001`), or while
   `PRIVACY_CONTACT_EMAIL` is unset (`accounts.E004`). Changing
   `POLICY_VERSION` later asks every user to accept again.

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

1. Set `DATABASE_URL` to the new database's internal connection string. Keep
   the connection string private; enter it directly in Render's environment
   settings and never paste it into chat or source control.
2. Set the other dashboard variables (table above).
3. Deploy. The build installs dependencies and collects static files; the
   pre-deploy step runs `migrate`, which on an empty database creates the
   accounts, couples, game, play and chat tables and loads the 3,105 questions
   (the original 1,917, 150 approved Truth or Dare dares, and 1,038 of the
   owner's new questions).
4. Create an admin: `python manage.py createsuperuser` (email and password).
5. Run the checks below.

## After every deploy: checks

- `python manage.py check --deploy` has no errors. `accounts.W001` is expected
  while email is intentionally disabled; otherwise verify the provider and
  sending-address warnings (`accounts.W002`/`W003`), and resolve the remaining
  database, proxy and policy warnings (`game.W001`/`W002`, `accounts.E001`-`E004`).
- The pre-deploy log shows `Purged N account(s) and N closed couple
  space(s).` (`purge_deleted_accounts` runs after `migrate`). It permanently
  deletes accounts deleted over 7 days ago and couple spaces closed over 30
  days ago. **On a database copied from elsewhere, spaces closed over 30
  days ago are deleted on the first deploy.**
- `/privacy/` shows the contact address and no yellow notes; `/terms/` is not
  published (deferred).
- When email is configured: test password recovery end to end. While it is
  disabled, the app clearly states password recovery is unavailable.
- The site loads over HTTPS, and `/admin/` is not the admin path.
- Two browsers on the same couple: Next on one shows the question on the
  other (WebSockets work).
- A new couple's first load in "Questions" mode shows 889 left: 890
  questions, with the first one on the card.
- In "Questions" mode, answer on one device: the other shows "<name> has
  answered." but not the answer, until it answers too.
- Chat: a message sent on one device arrives on the other with an unread
  badge, and presence shows where the partner is. If chat says "Chat isn't
  set up on this server yet", `CHAT_ENCRYPTION_KEYS` is missing.

## Backups

- The selected free database plan has no backups. Database expiry or loss can
  permanently erase beta accounts and game data. For a plan with backups,
  verify the schedule and retention, and **take a manual backup immediately
  before any deploy that changes the schema**:

  ```bash
  pg_dump --format=custom --no-owner "$DATABASE_URL" > backup-$(date +%Y%m%d-%H%M).dump
  ```

- Before relying on backups, restore one into a throwaway database once
  (`pg_restore --no-owner -d <throwaway url> backup.dump`) to prove they work.

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
