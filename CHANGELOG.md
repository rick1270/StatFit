# StatFit Changelog

## Session 2026-09-25 (Cloud Run hourly execution — code, not yet provisioned)

### Changes
- Rick wants StatFit running hourly without keeping a local machine on. Chose Google Cloud Run
  Jobs + Cloud Scheduler over local launchd/cron, GitHub Actions, or AWS — stays in the existing
  GCP project (`statfit-509421`) that already hosts the Sheets service account.
- **Design decision**: reuse `statfit-sync@statfit-509421.iam.gserviceaccount.com` as the Cloud
  Run Job's runtime identity instead of creating a new service account. No need to re-share the
  Sheet, and no JSON key material has to leave the laptop — the job authenticates via Application
  Default Credentials in the cloud. `statfit/sheets_writer.py::connect_sheet()` now checks
  whether the local key file exists and falls back to `google.auth.default()` if not.
- Added `statfit/cloud_state.py` (`download_state()`/`upload_state()`) and
  `cloud_run_entrypoint.py`: Cloud Run Jobs have no persistent disk between executions, so state
  (`sync_state.json`, cached garth session) round-trips through a GCS bucket each run. State is
  always uploaded in a `finally`, even on partial sync failure, so the garth session and
  watermark aren't lost. `data/fit_files/` intentionally does not round-trip — it was already
  ephemeral/redownloaded-per-run locally.
- Added `Dockerfile` + `.dockerignore` for the container image (deployed via `gcloud run jobs
  deploy --source .`, which builds through Cloud Build automatically).
- Added `google-cloud-storage` to `requirements.txt` (regenerated via `pip freeze`).
- **Not yet provisioned**: the actual GCP resources (state bucket, two Secret Manager secrets
  for Garmin email/password, the Cloud Run Job, the Cloud Scheduler job) don't exist yet —
  `gcloud` CLI isn't installed locally, that's the next step. Local `main.py`/`build_daily.py`
  are unaffected and still what's actually running today.
- Flagged as a known risk, not a blocker: Cloud Run's outbound IP is a shared Google NAT range
  rather than a dedicated IP, which could interact with Garmin's rate-limiting differently than
  the local machine's home IP (we already hit one transient 429 locally on 2026-09-22).

---

## Session 2026-09-23 (Daily tab)

### Changes
- Added `statfit/daily.py` + `build_daily.py`: builds a derived **Daily** tab, one row per
  calendar day (newest first), combining sleep/weight/primary-activity metrics from the raw
  Activities/Sleep/Weight tabs. Rationale: those source tabs are 70-100 columns wide and
  awkward to scan or read programmatically for recent data.
  - Fully rebuilt (clear + rewrite) on every run rather than upserted — it's a computed view,
    not synced source data. Not wired into `sync.run()`; run manually.
  - Primary-activity selection per day: prefers `running`/`treadmill_running`, else longest
    `total_timer_time`; fishing/diving never count as primary, only set `fished`/`dove` flags.
  - Found and worked around a `sync_weight()` quirk: the Weight tab's `date` column ends up as
    epoch-ms instead of a date string, because `_flatten_scalars(entry)` overwrites the
    `calendarDate`-derived `date` field with the entry's own raw `date` field. `daily.py` joins
    on `calendarDate` instead rather than fixing the upstream field ordering.
  - Verified output by hand: pace math, fishing-day/multi-activity-day edge cases, blank-field
    handling for days with only sleep/weight (no activity) all checked out.
- Confirmed (not a StatFit bug): Weight has no rows after 2026-08-05 — Rick is tracking that
  separately as an outside/device issue. `avgOvernightHrv`/`hrvStatus` are only ~46% populated
  even within 2026, suggesting a device/feature that came online partway through the year.

---

## Session 2026-09-22 (first live run)

### Changes
- Set up real credentials: `.env` (Garmin login) and `service_account.json` (Google service
  account key), both gitignored as intended.
- Created the target Google Sheet and shared it with the service account's `client_email`.
- **First live sync completed**: 271 activities, 366 sleep days, 117 weight entries synced over
  a 1-year backfill (`INITIAL_SYNC_DAYS=365`). Resolves the "not yet run against real
  credentials" item from Known Issues.
- Noted for later: Garmin's mobile login endpoint returned a transient `429 Too Many Requests`
  on an early attempt (IP rate-limited); it cleared on retry. Not investigated further since it
  self-resolved, but worth knowing if login starts failing repeatedly.
- `state/sync_state.json` now holds `last_synced_date: 2026-09-22` — future runs sync
  incrementally from there.

---

## Session 2026-09-21 (v0.1 — initial scaffold)

### Changes
- **Initial build**: Garmin Connect → Google Sheets sync tool, built from scratch as a new repo
  (separate from `life-fitness`, which previously removed Garmin scraping in favor of Strava —
  StatFit intentionally goes back to Garmin/FIT directly because Strava's API doesn't expose
  FIT-level detail like running dynamics, training effect, or HRV).
  - `garmin_client.py`: login via `garminconnect`/`garth` with cached session token, activity
    listing, original FIT download (unzips Garmin's `ORIGINAL` download format), sleep and body
    composition fetch.
  - `fit_decoder.py`: decodes FIT `session` and `lap` messages generically via `fitparse` — no
    fixed schema, since field sets vary by device/activity type. Tested against real FIT files
    (running, paddleboarding); confirmed it surfaces fields Strava's API doesn't (training
    effect, anaerobic training effect, temperature, fractional cadence). Filters out
    all-`None` tuple fields (e.g. running-power-phase fields on devices without that sensor)
    that would otherwise serialize as garbage strings.
  - `sheets_writer.py`: upserts rows into Activities/Laps/Sleep/Weight tabs via `gspread` +
    service account auth, growing the header row dynamically as new fields appear.
  - `sync.py` / `main.py`: incremental sync loop, state tracked in `state/sync_state.json`.
    Per-activity FIT decode failures are caught and skipped rather than crashing the whole sync.
  - Scope decision: pull everything available for now (activities, sleep, weight) — Rick will
    review real output and narrow to a curated column subset later.
  - Repo created locally, then pushed to `https://github.com/rick1270/StatFit`.
- Not yet run against real Garmin credentials or a live Google Sheet — `.env` and a Google
  service account still need to be set up.

---
