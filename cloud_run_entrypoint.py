import os
import sys
import traceback

from statfit import cloud_state, daily, sheets_writer, sync

BUCKET = os.environ["STATFIT_STATE_BUCKET"]


def main() -> None:
    cloud_state.download_state(BUCKET)

    failed = False
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
    except Exception:
        traceback.print_exc()
        failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
