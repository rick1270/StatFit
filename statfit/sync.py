import datetime
import json
from typing import Any

from statfit import config, fit_decoder, garmin_client, sheets_writer

DATE_FMT = "%Y-%m-%d"


def _today() -> datetime.date:
    return datetime.date.today()


def load_state() -> dict[str, str]:
    if config.SYNC_STATE_FILE.exists():
        return json.loads(config.SYNC_STATE_FILE.read_text())
    start = (_today() - datetime.timedelta(days=config.INITIAL_SYNC_DAYS)).strftime(DATE_FMT)
    return {"last_synced_date": start}


def save_state(state: dict[str, str]) -> None:
    config.SYNC_STATE_FILE.write_text(json.dumps(state, indent=2))


def _flatten_scalars(d: dict[str, Any]) -> dict[str, Any]:
    """Keep only scalar top-level fields; nested dicts/lists need bespoke
    handling per-endpoint since their shape varies."""
    return {k: v for k, v in d.items() if v is None or isinstance(v, (str, int, float, bool))}


def sync_activities(client, sheet, start_date: str, end_date: str) -> int:
    activities_ws = sheets_writer.ensure_worksheet(sheet, "Activities")
    laps_ws = sheets_writer.ensure_worksheet(sheet, "Laps")

    activities = garmin_client.list_activities_since(client, start_date, end_date)
    activity_rows = []
    lap_rows = []

    for activity in activities:
        activity_id = activity["activityId"]
        try:
            fit_path = garmin_client.download_fit(client, activity_id)
            decoded = fit_decoder.decode_fit(fit_path)
        except Exception as exc:
            print(f"  skipping activity {activity_id} ({activity.get('activityName')}): {exc}")
            continue

        row = {
            "activity_id": activity_id,
            "activity_name": activity.get("activityName"),
            "activity_type": (activity.get("activityType") or {}).get("typeKey"),
            "start_time_local": activity.get("startTimeLocal"),
        }
        row.update(decoded["session"])
        activity_rows.append(row)

        for lap in decoded["laps"]:
            lap_row = {"activity_id": activity_id, "lap_key": f"{activity_id}_{lap['lap_index']}"}
            lap_row.update(lap)
            lap_rows.append(lap_row)

    if activity_rows:
        sheets_writer.upsert_rows(activities_ws, activity_rows, key_field="activity_id")
    if lap_rows:
        sheets_writer.upsert_rows(laps_ws, lap_rows, key_field="lap_key")

    return len(activity_rows)


def sync_sleep(client, sheet, start_date: str, end_date: str) -> int:
    sleep_ws = sheets_writer.ensure_worksheet(sheet, "Sleep")

    start = datetime.datetime.strptime(start_date, DATE_FMT).date()
    end = datetime.datetime.strptime(end_date, DATE_FMT).date()

    rows = []
    day = start
    while day <= end:
        date_str = day.strftime(DATE_FMT)
        data = garmin_client.get_sleep(client, date_str)
        daily = (data or {}).get("dailySleepDTO") or {}
        if daily:
            row = {"date": date_str}
            row.update(_flatten_scalars(daily))
            row.update(_flatten_scalars({k: v for k, v in (data or {}).items() if k != "dailySleepDTO"}))
            rows.append(row)
        day += datetime.timedelta(days=1)

    if rows:
        sheets_writer.upsert_rows(sleep_ws, rows, key_field="date")
    return len(rows)


def sync_weight(client, sheet, start_date: str, end_date: str) -> int:
    weight_ws = sheets_writer.ensure_worksheet(sheet, "Weight")

    data = garmin_client.get_body_composition(client, start_date, end_date)
    entries = (data or {}).get("dateWeightList") or []

    rows = []
    for entry in entries:
        row = {"date": entry.get("calendarDate") or entry.get("date")}
        row.update(_flatten_scalars(entry))
        rows.append(row)

    if rows:
        sheets_writer.upsert_rows(weight_ws, rows, key_field="date")
    return len(rows)


def run() -> None:
    state = load_state()
    start_date = state["last_synced_date"]
    end_date = _today().strftime(DATE_FMT)

    client = garmin_client.connect()
    sheet = sheets_writer.connect_sheet()

    n_activities = sync_activities(client, sheet, start_date, end_date)
    n_sleep = sync_sleep(client, sheet, start_date, end_date)
    n_weight = sync_weight(client, sheet, start_date, end_date)

    save_state({"last_synced_date": end_date})

    print(f"Synced {n_activities} activities, {n_sleep} sleep days, {n_weight} weight entries "
          f"({start_date} to {end_date}).")
