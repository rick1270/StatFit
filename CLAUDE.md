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
| Runtime | Local Python venv (`./venv`) — no hosted deployment |
| Run | `./venv/bin/python main.py` |
| Secrets | `.env` (Garmin email/password, Sheet ID, service account file path), `service_account.json` (Google service account key) — both gitignored |

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
statfit/
  config.py            — loads .env, defines paths (state/, data/fit_files/)
  garmin_client.py      — Garmin Connect login (cached session), activity/sleep/weight fetch, FIT download
  fit_decoder.py         — decodes FIT session + lap messages into dicts (fitparse)
  sheets_writer.py        — upserts rows into Google Sheet tabs, growing columns dynamically
  sync.py                  — orchestrates incremental sync, tracks state/sync_state.json
  daily.py                  — builds the "Daily" tab: one row per calendar day, derived from
                               Activities/Sleep/Weight (see Daily Tab section below)
requirements.txt       — pinned dependencies (regenerate with `pip freeze` after adding a package)
.env.example           — template for required secrets
CLAUDE.md              — this file
README.md              — current state and setup instructions
CHANGELOG.md           — session changes and decisions
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

- Run manually after `main.py` syncs new data: `./venv/bin/python build_daily.py`.
- Not currently wired into `sync.run()` — rerun it by hand when you want the Daily tab refreshed.
- Primary-activity selection per day: prefers `running`/`treadmill_running`; otherwise the
  longest `total_timer_time`. Fishing/diving activities never count as primary — they only set
  the `fished`/`dove` flags. Activity-derived columns (distance, pace, HR, etc.) reflect the
  primary activity only, not an aggregate across multiple activities that day.
- Weight's `date` column is epoch-ms (a `sync.py` field-ordering quirk — `sync_weight()` sets
  `date` from `calendarDate` but then overwrites it with the entry's own `date` field during
  `_flatten_scalars`), so `daily.py` joins on `calendarDate` instead. Known, not worth fixing
  since `calendarDate` works fine.
- Known gap as of 2026-09-22: Weight has no rows after 2026-08-05 — Rick is tracking that
  separately (upstream/device issue, not a StatFit bug). `avgOvernightHrv`/`hrvStatus` are also
  only partially populated even within 2026 (~46% of rows) — likely a device/feature that came
  online partway through the year.

## Known Issues

1. **Undecoded FIT fields** — fitparse can't map every field to a name; these surface as
   `unknown_<N>` with real values but no label. Cross-reference Garmin's FIT SDK profile if a
   specific one turns out to matter.
2. ~~Not yet run against real credentials/Sheet~~ — first live run completed 2026-09-22 (271
   activities, 366 sleep days, 117 weight entries synced over a 1-year backfill).

---

## Key Invariants

- Raw per-second FIT record streams are **never** synced to Sheets — only `session` and `lap`
  summary messages. Sheets isn't built for thousands of rows per activity; revisit only if a
  specific need for second-by-second data comes up.
- Sheet columns are **not fixed** — `sheets_writer.upsert_rows()` appends new columns as new FIT
  fields are encountered across activity types/devices. This is a deliberate v1 choice: pull
  everything for now, prune to a curated subset of columns once real output has been reviewed.
- `state/sync_state.json` holds `last_synced_date`; deleting it forces a full re-sync back to
  `INITIAL_SYNC_DAYS` (default 90, set in `.env`).
- Activities, Laps, Sleep, and Weight are separate Sheet tabs, each keyed on its own field
  (`activity_id`, `lap_key`, `date`, `date` respectively) for upsert matching.

---

## Session Continuity

At the start of each Claude session, read:
1. `CLAUDE.md` — protocols, deployment info, known issues
2. `README.md` — current state and what works
3. `CHANGELOG.md` — recent changes and decisions
