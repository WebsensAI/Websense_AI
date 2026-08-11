# Changelog

All changes below are additive/functional -- no routes were removed, no
folder structure was changed, and the project still runs with `py run.py`.

## Frontend

### `frontend/templates/dashboard.html`
- Removed the non-functional **Dashboard**, **Reports**, and **Profile** nav
  items (they had no links/routes behind them). Nav now only contains
  **Analyze** and **Logout**, both of which already worked.

### `frontend/templates/workpage.html`
- Added `data-category` attributes and keyboard-accessible
  (`tabindex`, `role="button"`, `aria-expanded`) markup to the four existing
  score cards so they can be clicked/tapped/keyboard-activated. Their visual
  appearance is unchanged.
- Added three new (initially hidden) containers below the score cards:
  - `#categoryDetail` -- the expandable detailed report for whichever card
    is selected (score, summary, problems, why they matter, recommendations,
    priority).
  - `#overallAssessment` -- the new "Overall AI Assessment" section
    (executive summary, strengths, weaknesses, business impact, AI
    suggestions, modernization recommendations, priority actions).
  - `#errorBanner` -- a friendly place to surface partial/degraded-analysis
    messages without breaking the rest of the page.

### `frontend/static/js/workpage.js`
- Kept all existing progress-bar and score-card-filling logic as-is.
- Added click/keyboard handlers on the score cards: clicking a card renders
  its detailed report below the four cards, toggles the card's active
  state, and clicking a different card swaps the report (only one open at a
  time; clicking the same card again closes it).
- Added rendering for the new "Overall AI Assessment" section using the
  `overall` object now returned by `/api/analyze`.
- Added defensive error handling: if `categories`/`overall` are missing or
  malformed, or the request fails outright, a friendly message is shown in
  `#errorBanner` and the four score cards (if already populated) stay
  visible instead of the page breaking.
- All dynamic text is HTML-escaped before insertion.

### `frontend/static/css/workpage.css`
- Added styles for: clickable/hoverable score cards with an `.active`
  state, the expandable category detail panel, priority badges
  (high/medium/low), the Overall AI Assessment section, and the error
  banner. Existing styles (score cards, progress bar, input box, dark
  theme, color variables) are untouched.

## Backend

### `backend/app/services/scoring.py`
- Added per-category detail builders (`_seo_details`, `_security_details`,
  `_accessibility_details`, `_performance_details`) that turn the *existing*
  pipeline output (crawl data, security findings, tech findings, the Groq
  content/UX analysis, browser test results) into a structured report per
  category: `score`, `summary`, `issues` (`problem` / `why_it_matters` /
  `priority`), and `recommendations`. No data is invented -- every issue
  traces back to a real finding already computed elsewhere in the pipeline.
- Added `_classify_issue` / `_general_issues_by_category`, a lightweight
  keyword classifier that routes the AI's general content/UX issues
  (`content_analysis["issues"]`) into the right category card.
- Added `_build_overall`, which assembles the new "Overall AI Assessment"
  (`executive_summary`, `strengths`, `weaknesses`, `business_impact`,
  `ai_suggestions`, `modernization`, `priority_actions`) from the category
  scores/issues and the existing Groq-generated `content_analysis["summary"]`
  and `modernization` data -- again, no new AI call and no fabricated data.
- `build_frontend_data(...)` now also returns `categories` and `overall` in
  addition to the original `score`, `label`, `metrics`, `recs`, `eff`, `ai`
  keys, which are unchanged so `promo_email_agent.py` keeps working exactly
  as before.

### `backend/app/services/ai_insights.py`
- Wrapped the Groq API call (`_ask_ai`) in a try/except that logs the
  technical error server-side and raises a small internal
  `AIUnavailableError`.
- `analyze_content_and_ux`, `analyze_tech_modernization`, and
  `synthesize_final_report` now catch `AIUnavailableError` and return a
  friendly, structurally-valid fallback instead of crashing the pipeline if
  the AI API is down/rate-limited/misconfigured.

### `backend/app/services/pipeline.py`
- Each pipeline stage (crawl, tech detection, security scan, AI content
  analysis, AI modernization analysis, Playwright browser tests) is now
  wrapped in its own try/except. If one stage fails unexpectedly, the
  technical error is logged server-side and the pipeline continues with a
  safe default for that stage instead of the whole scan failing -- so a
  visitor still gets results for everything that *did* succeed.

### `backend/app/routes/routes.py`
- `/api/analyze`'s top-level error handler now logs the full technical
  error/traceback server-side only and returns a short, user-friendly
  message to the frontend instead of the raw exception string.

## Notes
- No API endpoints were added, removed, or renamed.
- No environment variable usage changed.
- `recs`, `eff`, `ai`, `score`, `label`, `metrics` in the API response are
  unchanged in shape, so nothing else that reads them (e.g. the promo email
  agent) is affected.

---

# Update: MySQL Authentication Layer

Replaces the temporary JSON-file user store with a real MySQL database via
SQLAlchemy. `users_store.py` keeps the exact same public API
(`authenticate(email, password)` and `get_user(email)`), so `routes.py` and
every other caller needed **zero changes**.

## New files

### `backend/app/models/__init__.py`
- New empty package marker for the models package.

### `backend/app/models/user.py`
- New SQLAlchemy `User` model backing the `users` table:
  `id`, `name`, `email` (unique, indexed), `password_hash`, `created_at`.
- `User.to_dict()` returns a plain dict snapshot so callers never touch a
  detached ORM instance after its session closes.

### `backend/app/utils/db.py`
- New SQLAlchemy engine + session module:
  - **Connection pooling**: `pool_size`, `max_overflow`, `pool_timeout`,
    `pool_recycle`, plus `pool_pre_ping=True` so a stale/dropped connection
    is detected and replaced automatically instead of raising "MySQL
    server has gone away" mid-request.
  - **`init_db()`**: creates the `users` table automatically if it doesn't
    exist yet (safe to call on every startup).
  - **`session_scope()`**: a context manager used by every DB call --
    commits on success, rolls back on any error (transaction rollback),
    and converts a lost/unreachable database into a `DatabaseUnavailableError`
    that callers turn into a friendly message instead of a crash.

## Modified files

### `backend/app/config.py`
- Added MySQL settings, all overridable via environment variables:
  `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`,
  `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`.
- Builds `SQLALCHEMY_DATABASE_URI` from those (`mysql+mysqlconnector://...`),
  or you can set `DATABASE_URL` directly to override it entirely.

### `backend/app/utils/users_store.py`
- Rewritten to use SQLAlchemy/MySQL instead of `backend/data/users.json`.
- `authenticate(email, password)`:
  - Unknown email -> auto-creates the account (password hashed with
    Werkzeug's `generate_password_hash`, never stored in plaintext).
  - Known email -> validates via `check_password_hash`.
  - Duplicate-email race (two simultaneous first-logins for the same new
    email) is caught via `IntegrityError` on flush, rolled back, and
    resolved by re-reading the row the other request created -- no crash,
    no duplicate row. Verified under a real concurrent-thread test.
  - Any DB connection failure returns `(None, "We couldn't reach the
    database right now. Please try again in a moment.")` instead of
    raising.
- `get_user(email)`: returns a dict or `None`; returns `None` (and logs
  server-side) rather than raising if the database is unreachable.

### `backend/app/app.py`
- Calls `init_db()` on app startup so the `users` table is created
  automatically. If MySQL isn't reachable yet, this logs the error instead
  of crashing the whole process at import time -- individual requests will
  still surface a friendly "couldn't reach the database" message.

### `backend/.env` / `backend/.env.example`
- Added `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` (local
  MySQL defaults: `localhost:3306`, user `root`, empty password, database
  `websense_ai`). Update these to match your actual MySQL server.
  `.env.example` also documents the optional pool-tuning variables and the
  `DATABASE_URL` override.

## Not changed
- `backend/data/users.json` is left in place but is **no longer read or
  written**; it's safe to delete once you've migrated any accounts you
  need (it was only ever a temporary store).
- `backend/app/routes/routes.py` -- untouched, as required, since it only
  calls `users_store.authenticate()` / relies on the `email`/`name` keys
  that are still present in the returned dict.

## How this was verified
Since this environment has no external network access to an existing MySQL
server, I installed MariaDB locally (MySQL wire-protocol compatible) and
ran it against the real code:
- Created the `users` table automatically via `init_db()` and confirmed its
  columns/types.
- First-login auto-registration, correct-password login, and
  incorrect-password rejection all behave as specified.
- Confirmed the stored `password_hash` is a real Werkzeug hash (not
  plaintext) and validates via `check_password_hash`.
- Simulated a **lost database connection** (pointed the engine at an
  unreachable host) and confirmed `authenticate()`/`get_user()` return a
  friendly error instead of raising.
- Fired 5 concurrent "first login" requests for the same brand-new email
  in separate threads to exercise the duplicate-email/race-condition path;
  all five resolved to a single user row with zero errors.
- Ran the full Flask app (`create_app()`) through login -> logout ->
  wrong-password -> correct-password -> `/api/session`, end to end.

You'll still need MySQL installed and reachable (and the `DB_*` values in
`.env` pointed at it) for this to work outside this environment --
`mysql-connector-python` and `SQLAlchemy` were already present in
`requirements.txt`, so no new dependencies were needed.

---

# Update: SMTP Reliability Overhaul (`promo_email_agent.py`)

Fixes the `Connection unexpectedly closed: The read operation timed out`
failure. Root cause: the original `send_email()` opened a brand-new
15-second-timeout connection per email with no retry, and on any failure
just logged `str(e)` and returned `False` -- so a single slow SMTP
handshake killed the send with no useful diagnosis and no second attempt.

## `backend/app/agents/promo_email_agent.py` (fully rewritten)

- **Detailed logging** -- switched from `print()` to the standard
  `logging` module (timestamps + levels), including debug-level logging
  of each EHLO/STARTTLS/NOOP response.
- **Separate failure detection**:
  - `auth_failed` -- `smtplib.SMTPAuthenticationError` (wrong
    password/App Password).
  - `timeout` -- a real read/connect timeout. Note: `smtplib` actually
    wraps a timeout during the initial connection as
    `SMTPServerDisconnected("Connection unexpectedly closed: timed
    out")` rather than raising a distinct timeout exception (confirmed
    this by reproducing the exact error message locally) -- so
    `_classify_error`/`_looks_like_timeout` specifically unwrap that
    case via the exception's `__context__`/`__cause__` (falling back to
    matching the message text) instead of misreporting it as a generic
    connection failure.
  - `tls_failed` -- `ssl.SSLError` / `smtplib.SMTPNotSupportedError`
    (STARTTLS not supported, cert validation failure, etc).
  - `connection_failed` -- refused/dropped connections.
  - `send_failed` -- other SMTP protocol errors (e.g. recipient
    refused).
  - `invalid_config` -- missing/malformed `SMTP_*` env vars, detected
    *before* any network call.
- **Retry with exponential backoff** -- up to 3 attempts, waiting 1s
  then 2s between retryable failures. `auth_failed` and `tls_failed` are
  **not** retried (a wrong password or unsupported server won't fix
  itself, and hammering a login endpoint risks a provider-side lockout);
  `send_failed` only retries on a 4xx (transient) SMTP response code,
  not a 5xx (permanent) one.
- **Connection reuse** -- a module-level cached `SMTP` connection
  (behind a lock, since `smtplib.SMTP` isn't thread-safe) is reused
  across sends, verified alive with `NOOP` before reuse, and
  transparently reopened if it's gone stale.
- **60-second timeout** -- up from 15s.
- **EHLO before *and* after STARTTLS** -- explicit `server.ehlo()` prior
  to `STARTTLS` (so the server can advertise it), then a required
  second `server.ehlo()` immediately after, per RFC 3207.
- **Credentials verified before sending** -- `_validate_config()` checks
  `SMTP_HOST`/`PORT`/`EMAIL`/`PASSWORD` are present and well-formed
  before opening a socket at all.
- **Never crashes** -- every public function is wrapped in a top-level
  `try/except`; `send_promo_email()` (called from a background thread)
  always returns a status dict, never raises.
- **Status codes instead of `True`/`False`** -- `send_email()` and
  `send_promo_email()` now return
  `{"status": "success" | "auth_failed" | "timeout" | "tls_failed" |
  "connection_failed" | "send_failed" | "invalid_config" |
  "skipped_no_recipient" | "unknown_error", "message": str, "attempts": int}`.
  (Nothing else reads this return value today -- it's fire-and-forget
  from `routes.py` -- so this is a non-breaking change; the richer
  status is there for whoever wires up logging/alerting next.)

## New files

### `backend/.env.smtp.example`
- Focused sample with just `SMTP_HOST`, `SMTP_PORT`, `SMTP_EMAIL`,
  `SMTP_PASSWORD`, plus step-by-step instructions for generating a
  Gmail App Password (2-Step Verification -> App Passwords -> paste the
  16-character code with spaces removed).

## Modified files

### `backend/.env.example` / `backend/.env`
- Added explicit `SMTP_HOST=smtp.gmail.com` and `SMTP_PORT=587` (these
  were previously only implicit via `config.py`'s defaults).

## How this was verified
No real SMTP/Gmail access from this environment, so I stood up a local
STARTTLS+AUTH test SMTP server (`aiosmtpd`, with a self-signed cert) and
a raw "black hole" TCP server that accepts connections but never
responds, and ran the real `promo_email_agent.py` against both:
- Successful send, and a second send reusing the cached connection
  (confirmed only 1 connection was opened for 2 sends).
- Wrong password -> `auth_failed`, exactly 1 attempt (no retry).
- Self-signed/untrusted cert -> `tls_failed` (real certificate
  validation, not mocked).
- Nothing listening on the port -> `connection_failed`, exactly 3
  attempts with ~1s + 2s backoff between them (~3s total, measured).
- Black-holed connection -> `timeout`, exactly 3 attempts -- this
  reproduced the user-reported `Connection unexpectedly closed: The read
  operation timed out` message verbatim, confirming both the fix and
  that it's now correctly classified as `timeout` rather than
  `connection_failed`.
- Missing `SMTP_PASSWORD` -> `invalid_config`, 0 network attempts made.
- Full `send_promo_email()` end-to-end (including its own AI-generation
  fallback, since Groq isn't reachable from this sandbox either) ->
  email delivered successfully to the test server.

---

# Update: Deterministic Scoring Pipeline

Fixes the same website producing different scores across repeated
analyses. See "Why scores were changing before" at the very end for the
full root-cause explanation -- summary: **AI-generated content was being
counted directly into the numeric score**, plus a `set()`-ordering issue
in two places and a browser-test timing race.

## Modified files

### `backend/app/services/scoring.py` (the primary fix)
- **`_seo_score()`** no longer subtracts `len(content_analysis["seo_gaps"])`.
  It now only reads `pages` (titles/meta descriptions actually
  crawled) -- 100% deterministic, no AI input. Signature changed from
  `_seo_score(pages, content_analysis)` to `_seo_score(pages)`.
- **`_accessibility_score()`** no longer subtracts
  `len(content_analysis["accessibility_gaps"])`. It now only reads
  `pages` (real alt-text data) and `test_results` (Playwright's DOM-level
  lang-attribute check) -- also AI-free. Signature changed from
  `_accessibility_score(pages, content_analysis, test_results)` to
  `_accessibility_score(pages, test_results)`.
  (`_security_score()` and `_technical_health_score()` were already
  AI-free and needed no change.)
- Added a **determinism contract** as a module docstring: the four
  `_*_score()` functions may only read from mechanical/deterministic
  inputs, never `content_analysis` or `modernization` (the two
  AI-generated inputs) -- so this can't silently regress later.
- Added `_finalize(items, key)`: dedupes AND sorts issue/recommendation
  lists by `(priority, text)` before they're returned. Every category's
  `issues`/`recommendations` (previously only `recommendations` was
  deduped, and neither was sorted) now goes through this, so the
  AI's array order and any accidental duplicate no longer affect what
  the user sees or in what order.
- `_general_issues_by_category()` now sorts the AI's raw `issues` array
  by `(page_url, issue text)` *before* classifying/bucketing them, so
  bucket contents don't depend on the AI's returned order either.
- `_build_recs()` (the top-level "recs" list) now sorts the AI's
  `issues`/`security_priorities` by severity+text before taking the
  top N (it was previously just "the first N in AI order"), dedupes the
  combined list by title, and sorts the final list by severity+title.

### `backend/app/services/analyze.py`
- `outdated_signals` was built as `list(set(outdated_signals))`.
  Iterating a Python `set` of strings is ordered by string hashes,
  which are randomized per-process (`PYTHONHASHSEED`) -- two runs of
  the app could produce the exact same signals in a different order.
  Changed to `sorted(set(outdated_signals))`: still dedupes, but the
  order is now fixed and reproducible.
- `technologies` and `header_hints` dicts are now returned via
  `dict(sorted(...))` for the same reason (defensive -- Python dicts
  already preserve insertion order, but that insertion order followed
  crawl order, which is now also sorted -- see below).
- Added a comment on `check_ssl_cert()` explaining why
  `datetime.utcnow()`-based `days_until_expiry` is intentionally *not*
  frozen: a certificate's real remaining lifetime is legitimately
  time-varying ground truth, not application-level nondeterminism.

### `backend/app/services/crawl.py`
- `links` per page was a `set()` converted to `list(links)` on the way
  out -- same hash-order issue as above. Changed to `sorted(links)`.
- The final `pages` and `errors` lists returned by `crawl_site()` are
  now sorted by URL before returning. BFS visiting order was already
  deterministic here (a plain FIFO list following `<a>` tag document
  order, not a set), but sorting the single choke point every caller
  reads from makes the guarantee explicit and protects against future
  changes (e.g. concurrent fetching) reintroducing order drift.

### `backend/app/services/ai_insights.py`
- Added `temperature=0` and a fixed `seed=42` to every Groq call, to
  minimize (not fully eliminate -- LLM inference isn't guaranteed
  bit-for-bit reproducible even at temperature 0, and Groq's `seed`
  support is itself best-effort) run-to-run wording/ordering drift in
  the AI's *text*.
- Added a module docstring making explicit that everything returned
  from this file is text/explanation only and must never feed into a
  numeric score.

### `backend/app/services/browser_tests.py`
- The console-error listener (`page.on("console", ...)`) was registered
  fresh on every page in the loop but **never removed** -- by page N,
  N stale listeners were still attached to the same `page` object.
  Now removed via `page.remove_listener(...)` after each page.
- `wait_until="networkidle"` only guarantees no network activity for
  500ms; it does **not** guarantee every console message a page will
  ever emit has already fired by the time it resolves. Reading
  `console_errors` immediately after `goto()` was a race -- whether a
  slightly-late console error got counted depended on timing. Added a
  fixed `page.wait_for_timeout(500)` settle window before reading
  results, and de-duped + sorted `console_errors`/`broken_images` so a
  message firing twice doesn't produce a timing-dependent count.
- Documented that this stage can never be *perfectly* deterministic --
  it drives a real browser against a real, live website, and that
  site's own third-party scripts/ads/A-B tests can genuinely behave
  differently between visits. What's fixed here is everything that was
  this code's own responsibility (the listener leak and the read race);
  what's left is inherent to auditing a live external site.

## Not changed
- `backend/app/services/pipeline.py` needed no changes -- it already
  ran every stage synchronously, in a fixed order, with no threading/
  async fan-out. It was correctly not a source of the problem, and I
  verified that by tracing every value it passes into `scoring.py`.
- Flask's dev server (`app.run(debug=True, port=5000)` in `run.py`) is
  single-process/single-threaded by default, so it wasn't a source of
  cross-request interference either -- ruled out, not a fix needed.

## How this was verified
- Ran `build_frontend_data()` 8 times for the *same* mechanical inputs
  (pages/security/tech findings) while feeding it **randomized AI
  output** each time (different issue counts, different order, different
  wording, different gap counts) -- confirmed the overall score and
  every per-category score were byte-identical across all 8 runs.
- Ran it again with the *same* AI issues shuffled into a different
  order each time, plus a duplicate issue mixed in -- confirmed the
  displayed issue order was identical across 6 runs and the duplicate
  collapsed to a single entry.
- Called `detect_technologies()` 20 times with the same input and
  confirmed `outdated_signals` came back in the exact same order every
  time (previously order-dependent on the process's hash seed).
- Mocked `crawl_site()`'s HTTP layer with a tiny 3-page site whose links
  appear in *non-alphabetical* HTML order (`/zebra` before `/apple`) and
  confirmed the returned `pages` list is nonetheless alphabetically
  sorted.
- Ran a full Flask `/api/analyze` integration test (via `create_app()`
  against a real MySQL instance, mocking only `run_pipeline_core`) six
  times with randomized AI content each call -- confirmed the score in
  the actual HTTP JSON response was identical every time.

## Why the scores were changing before (root cause)

There were three real, independent sources of nondeterminism, in order
of impact:

1. **AI-generated findings feeding directly into the numeric score (the
   main cause).** `_seo_score()` and `_accessibility_score()` both did
   `score -= min(len(content_analysis["...gaps"]) * 8, 30)`, where
   `content_analysis` is the parsed JSON output of a Groq LLM call. That
   call had no `temperature`/`seed` set, so it's ordinary LLM sampling:
   asking the same question about the same website twice does not
   reliably return a list of the same *length*. One run might return 2
   `seo_gaps`, the next run 4, for the exact same input pages -- and
   because the score formula subtracted 8 points per gap, the score
   itself would shift by up to ~16 points between otherwise-identical
   runs. This is the one that actually explains a visibly different
   *score*, not just different wording. Fix: numeric scoring no longer
   reads `content_analysis` (or `modernization`) at all -- see the
   determinism contract at the top of `scoring.py`.

2. **`list(set(...))` used for "dedupe" in two places**
   (`outdated_signals` in `analyze.py`, `links` in `crawl.py`). Python
   randomizes string hashing per process (`PYTHONHASHSEED`) as a
   security measure, so iterating a `set` of strings gives a different
   order in different runs of the app. This didn't move the *score* by
   itself (only `len()` was used for scoring there), but it did mean the
   *displayed* order of findings could shift between server restarts,
   and it was exactly the kind of latent bug that becomes a real score
   bug the moment someone (reasonably) writes `[:N]` to take "the top N"
   without sorting first -- which is precisely what was happening one
   layer up in `_build_recs()`/the per-category issue lists, now fixed
   with `_finalize()`.

3. **A timing race in the Playwright browser tests.** The console-error
   listener was read immediately after `page.goto(..., wait_until=
   "networkidle")` returned, but `networkidle` only promises 500ms of
   *network* silence -- it says nothing about whether every console
   message the page will ever log has fired yet. Whether a
   slightly-late JS error got captured was a coin flip based on exact
   timing, and `pages_with_errors` feeds directly into
   `_technical_health_score()`. Combined with a second bug (the console
   listener was never removed between pages, so listeners accumulated),
   this made the "Performance" category score noisier than it should
   have been run to run.

Everything else that looked suspicious turned out **not** to be a bug:
crawl order was already a deterministic FIFO walk following a fixed
HTML document's link order (not concurrent, not a set); Python dicts
have preserved insertion order since 3.7 so plain `dict` usage
elsewhere was fine; `pipeline.py` runs every stage synchronously with
no async/threading fan-out; and Flask's dev server is single-threaded
by default. The one legitimate, intentional exception is SSL
certificate expiry (`datetime.utcnow()`-based) -- that's supposed to
change as real time passes, and is explicitly called out as such
rather than "fixed."
