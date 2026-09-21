import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

GARMIN_EMAIL = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD = os.environ["GARMIN_PASSWORD"]

GOOGLE_SERVICE_ACCOUNT_FILE = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

INITIAL_SYNC_DAYS = int(os.environ.get("INITIAL_SYNC_DAYS", "90"))

STATE_DIR = ROOT_DIR / "state"
DATA_DIR = ROOT_DIR / "data"
FIT_DIR = DATA_DIR / "fit_files"
GARTH_SESSION_DIR = STATE_DIR / ".garth"
SYNC_STATE_FILE = STATE_DIR / "sync_state.json"

STATE_DIR.mkdir(exist_ok=True)
FIT_DIR.mkdir(parents=True, exist_ok=True)
