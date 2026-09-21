# StatFit

Syncs Garmin Connect data (activities decoded from raw FIT files, sleep, weight/body composition)
to a Google Sheet — like `life-fitness`'s Strava sync, but pulling richer metrics directly from
FIT files that Strava's API doesn't expose (running dynamics, training effect, respiration,
temperature, precise laps, etc.).

## How it works

- `statfit/garmin_client.py` — logs into Garmin Connect (session token cached locally so you're
  not re-authenticating/hitting MFA every run), lists activities, downloads original `.fit` files,
  fetches sleep and body composition data.
- `statfit/fit_decoder.py` — decodes a `.fit` file's `session` (activity summary) and `lap` messages
  into plain dicts using [fitparse]. Field sets vary by device/activity type — decoded fields are
  the FIT SDK's own names. Fields fitparse can't map to a known name show up as `unknown_<N>`; you
  can cross-reference Garmin's FIT SDK profile later if a specific one turns out to matter.
  Raw per-second record streams are **not** decoded — Sheets isn't built for thousands of rows per
  activity. Revisit if you need second-by-second data.
- `statfit/sheets_writer.py` — upserts rows into Google Sheet tabs (`Activities`, `Laps`, `Sleep`,
  `Weight`). New fields encountered get appended as new columns automatically, since the FIT field
  set isn't fixed up front — this is v1's "get everything, narrow down later" approach.
- `statfit/sync.py` — orchestrates an incremental sync: tracks the last-synced date in
  `state/sync_state.json` and only fetches new data since then.

## Setup

1. **Python env** (already created if you're reading this after initial build):
   ```
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ```

2. **Garmin credentials**: copy `.env.example` to `.env` and fill in `GARMIN_EMAIL` /
   `GARMIN_PASSWORD`.

3. **Google Sheet + service account**:
   - Create a Google Cloud service account, enable the Sheets API, download its JSON key.
   - Save the key as `service_account.json` in this repo root (gitignored).
   - Create a new Google Sheet, share it with the service account's `client_email` (Editor access).
   - Put the Sheet ID (from its URL) in `.env` as `GOOGLE_SHEET_ID`.

4. **Run**:
   ```
   ./venv/bin/python main.py
   ```
   First run pulls `INITIAL_SYNC_DAYS` (default 90) days of history. Subsequent runs only sync
   since the last recorded sync date.

## Notes

- Garmin Connect has no official public API for this — `garminconnect` (built on `garth`) talks to
  the same undocumented endpoints the mobile app uses. It can break if Garmin changes their backend.
- Session tokens are cached in `state/.garth/` to avoid repeated logins/MFA prompts.
- Downloaded `.fit` files are cached in `data/fit_files/` (gitignored).
