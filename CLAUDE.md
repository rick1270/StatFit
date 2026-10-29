# CLAUDE.md — StatFit

## Critical Rules

- **Never paste code back to the user.** All changes go through direct file edits.
- **GitHub is source of truth for all docs** (README, CHANGELOG). `https://github.com/rick1270/StatFit`.
- **Never commit secrets.** `.env` (Garmin credentials), `service_account.json` (Google service
  account key), `state/` (session token cache + sync state), and `data/` (downloaded `.fit` files)
  are gitignored. Double-check before any `git add -A` that none of these are staged.

---

## Deployment

| Field | Value |
|---|---|
| GitHub | `https://github.com/rick1270/StatFit` |
| Local dev | Python venv (`./venv`) — `./venv/bin/python main.py` / `build_daily.py`, unchanged |
| Hosted runtime | Google Cloud Run Job `statfit-sync`, GCP project `statfit-509421`, region `us-central1`. Triggered on demand by the `statfit-trigger` service (see below), with Cloud Scheduler job `statfit-hourly` as a fallback — despite the name it now runs every 6 hours (`0 */6 * * *` UTC) |
| Notification trigger | Cloud Run service `statfit-trigger` (`trigger/`), URL `https://statfit-trigger-469071842624.us-central1.run.app`. Tasker + AutoNotification on Rick's Android phone POST to it when Garmin Connect posts "activity ready to view". Public (`--allow-unauthenticated`) but requires header `X-StatFit-Token` matching Secret Manager `statfit-trigger-token`. Runs as `statfit-trigger@statfit-509421.iam.gserviceaccount.com` (only `run.invoker` + `run.viewer` on the `statfit-sync` job). Skips if an execution is running (concurrent runs would race on `sync_state.json` and could duplicate Sheet rows) or started within `DEBOUNCE_SECONDS` (120) |
| Local secrets | `.env` (Garmin email/password, Sheet ID, service account file path), `service_account.json` (Google service account key) — both gitignored |
| Cloud secrets | Secret Manager: `statfit-garmin-email`, `statfit-garmin-password`. No JSON key in the cloud — the job runs as `statfit-sync@statfit-509421.iam.gserviceaccount.com` itself (Application Default Credentials); see `statfit/sheets_writer.py::connect_sheet()` |
| Cloud state | GCS bucket `gs://statfit-509421-state/state/` mirrors what `state/` holds locally (`sync_state.json`, cached garth session) — Cloud Run Jobs have no persistent disk between executions, so `cloud_run_entrypoint.py` pulls it down before syncing and pushes it back up after, always (even on partial failure) |

### Redeploying after code changes

```
gcloud run jobs deploy statfit-sync --source . --region us-central1 \
  --service-account statfit-sync@statfit-509421.iam.gserviceaccount.com \
  --set-env-vars GOOGLE_SHEET_ID=...,GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json,INITIAL_SYNC_DAYS=90,STATFIT_STATE_BUCKET=statfit-509421-state \
  --set-secrets GARMIN_EMAIL=statfit-garmin-email:latest,GARMIN_PASSWORD=statfit-garmin-password:latest \
  --max-retries 0 --task-timeout 600
```
(`--source .` builds via Cloud Build automatically — no manual Docker/Artifact Registry steps.)

Redeploying the trigger service (only needed when `trigger/` changes):
```
gcloud run deploy statfit-trigger --source trigger --region us-central1 \
  --service-account statfit-trigger@statfit-509421.iam.gserviceaccount.com \
  --set-secrets TRIGGER_TOKEN=statfit-trigger-token:latest \
  --allow-unauthenticated --max-instances 1 --memory 256Mi
```

Manual trigger: `gcloud run jobs execute statfit-sync --region us-central1 --wait`
Logs: Cloud Run Console → Jobs → `statfit-sync` → Executions (or `gcloud logging read`).

---

## Development Workflow

**Standard workflow:**
1. Create a feature branch in git
2. Edit code locally in `statfit/`
3. Run `./venv/bin/python main.py` (or targeted module tests) against real data to verify
4. When satisfied: merge to `main`
5. Push to GitHub (`git push`)

There is no separate deploy step — `main` on GitHub and the local checkout are the only two
states that matter. Whichever is currently checked out locally is "production" for this project.

---

## Repo Layout

```
main.py               — entry point, calls statfit.sync.run()
build_daily.py         — entry point, calls statfit.daily.build_daily() to (re)build the Daily tab
trigger/                — statfit-trigger Cloud Run service (main.py, Dockerfile, requirements.txt):
                          token-checked HTTP endpoint that starts the sync job; own image,
                          not part of the job's image
cloud_run_entrypoint.py — Cloud Run Job entry point: pulls state/ from GCS, runs sync + daily
                          build, pushes state/ back, always (see Deployment section above)
Dockerfile              — container image for the Cloud Run Job
.dockerignore            — excludes venv/, state/, data/, secrets from the image
statfit/
  config.py            — loads .env, defines paths (state/, data/fit_files/)
  garmin_client.py      — Garmin Connect login (cached session), activity/sleep/weight fetch, FIT download
  fit_decoder.py         — decodes FIT session + lap messages into dicts (fitparse)
  sheets_writer.py        — upserts rows into Google Sheet tabs, growing columns dynamically;
                             connect_sheet() uses the service account JSON key locally, falls
                             back to Application Default Credentials in Cloud Run
  sync.py                  — orchestrates incremental sync, tracks state/sync_state.json
  daily.py                  — builds the "Daily" tab (one row per calendar day) and "Weekly" tab
                               (one row per week of runs), derived from Activities/Sleep/Weight
                               (see Daily Tab section below)
  cloud_state.py             — download_state()/upload_state(): mirrors state/ to/from GCS,
                               used only by cloud_run_entrypoint.py
  splits.py                   — builds "Splits" tab rows (per-mile splits, computed in
                               fit_decoder._mile_splits) and fills treadmill elevation from the
                               Planned tab (see Splits Tab section below)
requirements.txt       — pinned dependencies (regenerate with `pip freeze` after adding a package)
.env.example           — template for required secrets
CLAUDE.md              — this file
README.md              — current state and setup instructions
CHANGELOG.md           — session changes and decisions
dev_Instructions       — Rick's original spec for the Daily tab (columns, primary-activity rules)
```

`state/` and `data/` are created at runtime (gitignored) — not present in a fresh clone until
`main.py` is run once.

---

## Daily Tab

`build_daily.py` (`statfit/daily.py`) builds a derived **"Daily"** tab: one row per calendar day,
newest first, pulling from the raw Activities/Sleep/Weight tabs (which are ~70-100 columns wide
and awkward to read programmatically). Unlike the other tabs, Daily is fully **rebuilt from
scratch on every run** (clear + rewrite), not upserted — it's a computed view, not synced source
data.

- Run manually after `main.py` syncs new data: `./venv/bin/python build_daily.py` (builds both
  Daily and Weekly). In the cloud, `cloud_run_entrypoint.py` rebuilds both after every sync.
- Blood pressure: `bp_systolic` / `bp_diastolic` / `bp_pulse` are the mean of that day's
  BloodPressure readings (keyed on the reading's local date); `bp_readings` is the count.
- Not wired into `sync.run()` itself — local runs need `build_daily.py` by hand.
- Body composition: `body_fat_pct` is Weight.`bodyFat` (already %); `muscle_lbs` is
  Weight.`muscleMass` (grams) / 453.592.
- `cadence_spm` is steps/min: FIT `avg_running_cadence` counts one foot, so it's
  2 × (`avg_running_cadence` + `avg_fractional_cadence`).
- `hr_first_half` / `hr_second_half` come from Activities columns of the same name, computed by
  `fit_decoder._hr_halves()` from the per-second record stream at decode time (time-weighted,
  split at the midpoint between first and last HR sample; gaps > 60s treated as pauses).
  `hr_drift` = second − first. Laps weren't usable for this: ~25% of runs have a single lap and
  lap boundaries rarely fall at the halfway point. Backfilled for all existing activities on
  2026-10-11 via `sheets_writer.update_columns()`. Caveat: wrist optical HR can lock onto cadence
  (~170-180 spm), which shows up as a sudden HR jump at steady pace — e.g. the 2026-10-03 run's
  54 bpm "drift". Not filtered.

### Weekly Tab

Also built by `daily.py` (`build_weekly()`), also cleared and rewritten every run. One row per
Monday-starting week, newest first, with zero rows kept for weeks without runs so gaps are
visible. Aggregates **every** `running`/`treadmill_running` activity that week (not just each
day's primary). Columns: `week_start`, `runs`, `miles`, `run_min`, `avg_pace`, `avg_hr`
(time-weighted by `total_timer_time`), `long_run_mi`, `avg_cadence_spm` (time-weighted).
- Primary-activity selection per day: prefers `running`/`treadmill_running`; otherwise the
  longest `total_timer_time`. Fishing/diving activities never count as primary — they only set
  the `fished`/`dove` flags. Activity-derived columns (distance, pace, HR, etc.) reflect the
  primary activity only, not an aggregate across multiple activities that day.
- Weight's `date` column is epoch-ms (a `sync.py` field-ordering quirk — `sync_weight()` sets
  `date` from `calendarDate` but then overwrites it with the entry's own `date` field during
  `_flatten_scalars`), so `daily.py` joins on `calendarDate` instead. Known, not worth fixing
  since `calendarDate` works fine.
- ~~Weight has no rows after 2026-08-05~~ — resolved upstream; entries resumed (14 rows
  2026-08-06 → 2026-10-26 as of 2026-10-26). `avgOvernightHrv`/`hrvStatus` are only partially
  populated even within 2026 (~46% of rows) — likely a device/feature that came online partway
  through the year.

### Splits Tab

One row per run (`sport == running`, outdoor and treadmill), keyed on `activity_id`, upserted by
`sync_activities()` like Activities/Laps. Columns: `activity_id, date, activity_type,
distance_mi, elev_source, partial_mi, partial_pace, partial_hr, partial_elev_ft`, then
`mile_N_pace, mile_N_hr, mile_N_elev_ft` for each full mile.
- Computed in `fit_decoder._mile_splits()` from the record stream: each mile crossing is
  interpolated between samples. Pace is **elapsed** time (pauses included — Rick's choice), HR is
  time-weighted (gaps > 60s skipped), elevation is **net** change in feet (end − start).
- Partial mile = leftover after the last full mile; dropped if < 0.05 mi (`MIN_PARTIAL_MI`).
- Partial columns come **before** the mile columns and are always present (blank if dropped):
  `upsert_rows()` appends unseen columns at the right, so `mile_11_*` etc. land after the
  existing mile columns when a longer run shows up.
- Treadmill: record distances are the watch's wrist estimate; Garmin replaces the session total
  with the treadmill's distance when entered at save. `_mile_splits()` scales record distances to
  the session total so splits match Activities/Daily and Planned's miles. The watch's error is
  assumed uniform across the run.
- Treadmill elevation (`elev_source = planned`): `splits.fill_treadmill_elevation()` derives net
  climb per mile from the Planned tab's segments (distance × incline), matched by date when
  there's exactly one treadmill plan and one treadmill run that day. Assumes the plan was run as
  written. Miles beyond the plan stay blank. Run after every rebuild (`build_daily.py`,
  `cloud_run_entrypoint.py`), so a plan entered after the run still lands — and a re-synced row
  (whose upsert blanks these cells) gets refilled.
- Activities with no record stream (manual Garmin Connect entries) get no Splits row.
- Backfilled 2026-10-26 for all existing runs.

### BloodPressure Tab

One row per reading, keyed on `measurement_key` (= `measurementTimestampGMT`; `version` looks
like an upload timestamp, so it's not a stable key), upserted by `sync_blood_pressure()`.
Leading columns `date` / `time_local` come from `measurementTimestampLocal`, then every scalar
field Garmin returns (`systolic`, `diastolic`, `pulse`, `category`, `sourceType`, ...).
- Source: Rick's Omron cuff → OMRON connect → Garmin Connect via [omramin](https://github.com/bugficks/omramin),
  installed at `~/.venvs/omramin` on the Mac (tokens in a plaintext file,
  `--keyring-backend file`; pass that flag on every command). Not automated — readings only
  reach Garmin (and then StatFit) when `omramin --keyring-backend file sync` is run.
- Fetched with a 30-day lookback behind the watermark (`sync.BP_LOOKBACK_DAYS`): since omramin
  runs by hand, readings reach Garmin late, and a scheduled run may already have advanced the
  watermark past their date (the 2026-10-28 22:15 reading was missed this way).
- Backfilled 2026-10-28 over the prior year — Garmin had one reading (that day's). Older Omron
  history pushed to Garmin later is beyond the lookback: rerun `sync.sync_blood_pressure()` with
  a wide date range.

### Tabs StatFit Doesn't Write

Added by hand / by other Claude sessions (2026-10). StatFit code never touches them, but some
depend on StatFit's output:

- **Trend Data** — `ARRAYFORMULA`s over Daily and Weekly. **They reference columns by letter**:
  Daily `A,I,J,L,M,N,O,Q` (date, weight_lbs, body_fat_pct, activity_type, distance_mi,
  duration_min, pace_min_mi, avg_hr) and Weekly `A,C,E,F,G` (week_start, miles, avg_pace, avg_hr,
  long_run_mi). **Only append new Daily/Weekly columns at the end — never insert or reorder**,
  or Trend Data silently reads the wrong data (no error). If a reorder is unavoidable, update the
  Trend Data formulas in the same change.
- **Dashboard** — settings + trend/projection/race-estimate formulas, all over Trend Data.
- **Labs** — manually entered lab results, one test per row.
- **Update Log / Check-In / Planned** — written by a separate daily-briefing assistant.
  Planned holds Claude-prescribed treadmill plans (incline isn't recorded by the device); StatFit
  reads it (never writes) to fill treadmill elevation in Splits — `segments` must keep the
  `0.50-2.75 @ 4.2mph 1.0%` format (falls back to `avg_incline_pct` over `distance_mi`). Its
  pace/time columns must be written as text (`14:23`), not user-entered — Sheets parses `43:08`
  as 43 hours.

## Known Issues

1. ~~Cloud Run deployment not yet provisioned~~ — deployed and verified 2026-09-26. Both a
   direct `gcloud run jobs execute` and an actual Cloud Scheduler-triggered run completed
   successfully end-to-end (synced data, rebuilt Daily, state round-tripped through GCS
   correctly). Runs hourly on the `0 * * * *` schedule from here on. (Since 2026-10-10:
   notification-triggered, with a 6-hourly fallback — see Deployment.)
2. Cloud Run's outbound IP is a shared Google NAT range, not a dedicated IP — small chance this
   looks different to Garmin than the local machine's home IP and affects rate-limiting behavior
   (we already hit one transient 429 locally). Mitigated by reusing the cached garth session
   (few real logins after the first) — worth knowing if login starts failing repeatedly after
   the cutover.
3. ~~Timezone bug dropped activities recorded late at night~~ — fixed 2026-10-01.
   `sync.py::_today()` used `datetime.date.today()`, which is the *container's* system date
   (UTC in Cloud Run) rather than Rick's local calendar day. Since the sync watermark
   (`sync_state.json`) advances to that date after every run, UTC midnight (8-9pm Eastern)
   permanently excluded any activity recorded later that Eastern evening — the watermark had
   already moved past "today" hours before the user's day was actually over. This ran
   correctly by accident when local (`./venv`), since the Mac's system clock was already
   Eastern. Fixed by adding `config.LOCAL_TZ` (`America/New_York`, overridable via
   `STATFIT_TIMEZONE`) and using `datetime.now(config.LOCAL_TZ).date()` instead. Added `tzdata`
   to `requirements.txt` since the slim container image may lack the system IANA database that
   `zoneinfo` needs.
3. **Undecoded FIT fields** — fitparse can't map every field to a name; these surface as
   `unknown_<N>` with real values but no label. Cross-reference Garmin's FIT SDK profile if a
   specific one turns out to matter.
4. ~~Not yet run against real credentials/Sheet~~ — first live run completed 2026-09-22 (271
   activities, 366 sleep days, 117 weight entries synced over a 1-year backfill).

---

## Key Invariants

- Raw per-second FIT record streams are **never** synced to Sheets — only `session` and `lap`
  summary messages, plus a few numbers derived from records at decode time (currently
  `hr_first_half`/`hr_second_half` and the Splits tab). Sheets isn't built for thousands of rows per activity; revisit only if a
  specific need for second-by-second data comes up.
- Sheet columns are **not fixed** — `sheets_writer.upsert_rows()` appends new columns as new FIT
  fields are encountered across activity types/devices. This is a deliberate v1 choice: pull
  everything for now, prune to a curated subset of columns once real output has been reviewed.
- `state/sync_state.json` holds `last_synced_date`; deleting it forces a full re-sync back to
  `INITIAL_SYNC_DAYS` (default 90, set in `.env`).
- Activities, Laps, Splits, Sleep, Weight, and BloodPressure are separate Sheet tabs, each keyed
  on its own field (`activity_id`, `lap_key`, `activity_id`, `date`, `date`, `measurement_key`
  respectively) for upsert matching.

---

## Session Continuity

At the start of each Claude session, read:
1. `CLAUDE.md` — protocols, deployment info, known issues
2. `README.md` — current state and what works
3. `CHANGELOG.md` — recent changes and decisions
