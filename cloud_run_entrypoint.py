import os
import subprocess
import sys
import traceback

from statfit import cloud_state, config, daily, sheets_writer, splits, sync

BUCKET = os.environ["STATFIT_STATE_BUCKET"]
OMRAMIN = "/opt/omramin/bin/omramin"
OMRAMIN_CONFIG = config.STATE_DIR / "omramin" / "config.json"


def push_omron_readings() -> bool:
    """Copy new Omron cuff readings from OMRON connect to Garmin Connect so
    sync.run() picks them up. omramin's config and login tokens live in
    state/omramin/ and round-trip through GCS like the garth session. If the
    OMRON token has expired, omramin tries to prompt and fails (no TTY) —
    re-login on the Mac and re-upload (see CLAUDE.md).

    StatFit's GARMIN_* env vars are withheld: omramin prefers them over its own
    config, and a mismatched email means it can't find its saved tokens."""
    if not OMRAMIN_CONFIG.exists():
        print("No omramin config in state/; skipping Omron sync.")
        return True
    result = subprocess.run(
        [OMRAMIN, "--config", str(OMRAMIN_CONFIG), "--keyring-backend", "file",
         "sync", "--days", "3"],
        env={k: v for k, v in os.environ.items() if not k.startswith("GARMIN_")},
        stdin=subprocess.DEVNULL, timeout=180,
    )
    return result.returncode == 0


def main() -> None:
    cloud_state.download_state(BUCKET)

    failed = False
    try:
        # A failed Omron sync shouldn't block the Garmin sync.
        if not push_omron_readings():
            print("omramin sync failed.")
            failed = True
    except Exception:
        traceback.print_exc()
        failed = True

    try:
        sync.run()
    except Exception:
        traceback.print_exc()
        failed = True
    finally:
        # Always persist whatever state exists (garth session refresh, or a
        # partially-advanced watermark), even if the sync itself failed.
        cloud_state.upload_state(BUCKET)

    try:
        sheet = sheets_writer.connect_sheet()
        n = daily.build_daily(sheet)
        print(f"Built Daily tab: {n} rows.")
        n = daily.build_weekly(sheet)
        print(f"Built Weekly tab: {n} rows.")
        n = splits.fill_treadmill_elevation(sheet)
        print(f"Filled treadmill elevation from Planned: {n} runs.")
    except Exception:
        traceback.print_exc()
        failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
