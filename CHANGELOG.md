# StatFit Changelog

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
