import zipfile
from io import BytesIO
from pathlib import Path

import garminconnect

from statfit import config


def connect() -> garminconnect.Garmin:
    """Log in to Garmin Connect, reusing a cached session token when possible
    so we don't hit MFA/login rate limits on every run."""
    client = garminconnect.Garmin(config.GARMIN_EMAIL, config.GARMIN_PASSWORD)
    token_dir = str(config.GARTH_SESSION_DIR)
    try:
        client.login(token_dir)
    except (FileNotFoundError, garminconnect.GarminConnectAuthenticationError):
        client.login()
        client.garth.dump(token_dir)
    return client


def list_activities_since(client: garminconnect.Garmin, start_date: str, end_date: str) -> list[dict]:
    """start_date/end_date as 'YYYY-MM-DD'."""
    return client.get_activities_by_date(start_date, end_date)


def download_fit(client: garminconnect.Garmin, activity_id: int | str) -> Path:
    """Download the original FIT file for an activity and save it to disk.
    Garmin serves 'ORIGINAL' downloads as a zip containing the .fit file."""
    raw = client.download_activity(
        str(activity_id), dl_fmt=garminconnect.Garmin.ActivityDownloadFormat.ORIGINAL
    )
    dest = config.FIT_DIR / f"{activity_id}.fit"

    with zipfile.ZipFile(BytesIO(raw)) as zf:
        fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
        if not fit_names:
            raise ValueError(f"No .fit file found in ORIGINAL download for activity {activity_id}")
        dest.write_bytes(zf.read(fit_names[0]))

    return dest


def get_sleep(client: garminconnect.Garmin, date: str) -> dict:
    """date as 'YYYY-MM-DD'."""
    return client.get_sleep_data(date)


def get_body_composition(client: garminconnect.Garmin, start_date: str, end_date: str) -> dict:
    return client.get_body_composition(start_date, end_date)
