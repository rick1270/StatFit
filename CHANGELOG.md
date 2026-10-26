# StatFit Changelog

## Session 2026-10-26 (sheet review + per-mile splits)

### Changes
- **Sheet review**: documented the tabs StatFit doesn't write (Dashboard, Trend Data, Labs,
  Update Log, Check-In, Planned) in CLAUDE.md. Trend Data references Daily/Weekly columns by
  letter — new Daily/Weekly columns must be appended, never inserted. Found Update Log's header
  one column short and Planned's pace/time entered as hours (`43:08` → 43h).
- **Splits tab**: one row per run with `mile_N_pace` / `_hr` / `_elev_ft` and a `partial_*`
  set for the leftover (dropped under 0.05 mi). Decisions: one row per run (not per mile), net
  elevation (not gain/loss), elapsed pace (pauses included).
- **Treadmill distance scaling**: every record/session distance mismatch among local runs (>20 m) was a
  treadmill run (session total replaced by the entered treadmill distance) or a manual entry
  with no records. Treadmill splits scale record distances to the session total.
- **Treadmill elevation from Planned**: distance × incline per plan segment, refilled every
  rebuild.

## Session 2026-10-11 (Daily additions + Weekly tab)

### Changes
- **Daily tab new columns**: `body_fat_pct`, `muscle_lbs` (from Weight), `cadence_spm`
  (steps/min = 2 × (`avg_running_cadence` + `avg_fractional_cadence`), since FIT cadence counts
  one foot), and `hr_first_half` / `hr_second_half` / `hr_drift` for the primary activity.
  Column order changed — anything referencing Daily columns by letter will have shifted.
- **First- vs second-half HR**: computed in `fit_decoder._hr_halves()` from the FIT record
  stream (time-weighted, split at the time midpoint), stored as two new Activities columns.
  Chose records over laps because 42 of 180 runs have a single lap and lap boundaries don't line
  up with the halfway point. Raw records still never go to Sheets.
- **Backfill**: one-off script decoded all 283 existing activities (local FIT files, plus 9 only
  ever synced in the cloud, downloaded fresh) — 279 got HR halves, 4 have no HR data. Written via
  new `sheets_writer.update_columns()`, which sets only the named cells; `upsert_rows()` would
  have rewritten whole rows and turned existing numbers into text.
- **Weekly tab**: new `daily.build_weekly()` — runs, miles, run_min, avg_pace, time-weighted
  avg_hr, long_run_mi, avg_cadence_spm per Monday-starting week (55 weeks). Built by both
  `build_daily.py` and `cloud_run_entrypoint.py`.
- Redeployed `statfit-sync` before writing the backfill, so a run of the old code couldn't
  blank the new HR columns on re-synced rows. Verified with a manual cloud execution: new
  activity got HR halves, Daily (385 rows) and Weekly (55 rows) rebuilt.
- Noted: the 2026-10-03 treadmill run shows 54 bpm drift (129 → 183) — HR jumped ~35 bpm within
  a minute at near-identical lap splits, which looks like wrist optical HR locking onto cadence
  rather than true drift. Not filtered; worth keeping in mind when reading `hr_drift`.

---

## Session 2026-10-10 (notification-triggered sync)

### Changes
- **On-demand trigger**: added `trigger/`, a small Cloud Run service (`statfit-trigger`) that
  starts the `statfit-sync` job when POSTed with a valid `X-StatFit-Token` header. Tasker +
  AutoNotification on Rick's Android phone call it when Garmin Connect posts an "activity ready
  to view" notification, so new activities land in the Sheet within minutes instead of up to an
  hour later.
  - Public endpoint with shared-secret auth (Secret Manager `statfit-trigger-token`) because
    getting a Google OAuth token from Tasker is impractical. The service starts the job as its
    own least-privilege service account `statfit-trigger@` (`run.invoker` + `run.viewer` on the
    job only).
  - Skips when an execution is still running (concurrent runs would race on `sync_state.json`
    in GCS and could append duplicate Sheet rows) or started within 120s (debounces bursts of
    notifications when several activities sync at once).
  - Verified: bad token → 401; valid token → job started; immediate repeat → skipped.
- **Fallback schedule**: Cloud Scheduler `statfit-hourly` changed from hourly to every 6 hours
  (`0 */6 * * *` UTC). Kept as a safety net for missed notifications and for sleep/weight data,
  which don't generate the activity notification. Job name left as-is to avoid recreating it.
- **Phone setup verified (2026-10-11)**: Tasker + AutoNotification configured to fire on *all*
  Garmin Connect notifications (extra triggers are harmless — skipped by the in-progress /
  120s debounce check). First phone-triggered run (`statfit-sync-kdv7v`) completed successfully.
  Early phone attempts returned 405/404 (GET instead of POST) and 401 (token mismatch) before the
  Tasker task was corrected.
- **Trigger logging fix**: set `PYTHONUNBUFFERED=1` in `trigger/Dockerfile` — gunicorn was
  buffering `print()` output, so Started/Skipped lines reached Cloud Logging minutes late,
  making it hard to match phone requests to job executions. Redeployed `statfit-trigger`.

---

## Session 2026-10-01 (timezone bug — activities dropped overnight)

### Changes
- Rick reported a fishing activity from the previous night missing, and other activities
  seeming "delayed." Root cause: `statfit/sync.py::_today()` used `datetime.date.today()`,
  which reflects the *execution environment's* system date — UTC in the Cloud Run container,
  not Rick's Eastern local calendar day. Ran correctly by accident when sync only ran locally
  (the Mac's system clock is already Eastern).
  - The sync watermark (`state/sync_state.json`'s `last_synced_date`) advances to "today" after
    every run. In UTC, midnight is 8-9pm Eastern — so from that point each night until actual
    local midnight, the watermark had already moved past the user's still-ongoing calendar day,
    permanently excluding anything recorded in that ~4-hour gap (Garmin tags activities by local
    date, not UTC).
  - Fix: added `config.LOCAL_TZ` (`America/New_York`, overridable via `STATFIT_TIMEZONE` env
    var) and changed `_today()` to `datetime.datetime.now(config.LOCAL_TZ).date()`. Added
    `tzdata` to `requirements.txt` as a safety net, since minimal container base images don't
    always ship the system IANA timezone database that `zoneinfo` depends on.
  - Redeployed the fixed code to the Cloud Run Job.
  - Recovery: rolled `sync_state.json` in the GCS state bucket back to `2026-09-29` (idempotent
    — upserts by `activity_id`/`date` mean re-fetching already-synced days is harmless) so the
    next run re-covers the gap and picks up the missing fishing activity.
- This is a cloud-migration-specific class of bug worth remembering: anything using "today"/
  calendar-day logic needs to be explicit about *whose* calendar day once the code runs
  somewhere other than the user's own machine.

---

## Session 2026-09-26 (Cloud Run hourly execution — provisioned and live)

### Changes
- Finished provisioning the GCP infrastructure designed in the previous session:
  - Billing was unlinked on `statfit-509421` (an old billing account existed but was closed);
    Rick linked a new open billing account.
  - Enabled Cloud Run, Cloud Build, Cloud Scheduler, Secret Manager, Storage APIs.
  - Created `gs://statfit-509421-state`, seeded it with the current local `state/` (sync
    watermark + cached garth session) so the first cloud run resumed incrementally instead of
    re-logging in and re-backfilling a year of history.
  - Created Secret Manager secrets `statfit-garmin-email`/`statfit-garmin-password`; granted
    `statfit-sync@...` service account `secretAccessor` on both plus `storage.objectAdmin` on
    the state bucket.
  - Deployed Cloud Run Job `statfit-sync` via `gcloud run jobs deploy --source .` (Cloud Build
    handled the container build automatically, no manual Docker/Artifact Registry steps).
  - Created Cloud Scheduler job `statfit-hourly` (`0 * * * *`), OAuth-triggering the Cloud Run
    Job as the same service account (granted `run.invoker` on the job).
- **Verified end-to-end**: a direct `gcloud run jobs execute` completed successfully (correctly
  resumed from the seeded watermark, synced only new data, rebuilt Daily). Separately confirmed
  the actual Cloud Scheduler → Cloud Run OAuth path also works (`gcloud scheduler jobs run`
  produced a real execution, run by the service account, matching the scheduler's
  `lastAttemptTime`).
- Incidentally triggered two near-simultaneous executions during verification (one via direct
  REST call testing the endpoint, one the delayed scheduler trigger landing) — both completed
  successfully with no state corruption, confirming the sync's upsert-based design tolerates
  accidental overlap. Not a concern for real hourly cadence, which only fires once per hour.
- StatFit now runs hourly without any local machine needing to be on. Local `main.py`/
  `build_daily.py` remain fully functional for dev/testing.

---

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
