import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# .strip(): the Secret Manager values may carry a trailing newline (the email does).
GARMIN_EMAIL = os.environ["GARMIN_EMAIL"].strip()
GARMIN_PASSWORD = os.environ["GARMIN_PASSWORD"].strip()

GOOGLE_SERVICE_ACCOUNT_FILE = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

INITIAL_SYNC_DAYS = int(os.environ.get("INITIAL_SYNC_DAYS", "90"))

# "Today" for sync purposes must be Rick's local calendar day, not whatever
# timezone the process happens to run in. This matters now that sync runs in
# a Cloud Run container (UTC) rather than the local machine (was previously
# always correct by accident, since the Mac's system clock is already local
# time). Getting this wrong permanently drops activities recorded in the
# gap between UTC midnight and local midnight — the watermark advances past
# them before the user's day is actually over.
LOCAL_TZ = ZoneInfo(os.environ.get("STATFIT_TIMEZONE", "America/New_York"))

STATE_DIR = ROOT_DIR / "state"
DATA_DIR = ROOT_DIR / "data"
FIT_DIR = DATA_DIR / "fit_files"
GARTH_SESSION_DIR = STATE_DIR / ".garth"
SYNC_STATE_FILE = STATE_DIR / "sync_state.json"

STATE_DIR.mkdir(exist_ok=True)
FIT_DIR.mkdir(parents=True, exist_ok=True)
