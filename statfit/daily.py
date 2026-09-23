import datetime
from typing import Any, Optional

import gspread

from statfit import sheets_writer

COLUMNS = [
    "date", "resting_hr", "sleep_hours", "deep_hours", "rem_hours", "bedtime",
    "sleep_stress", "overnight_hrv", "weight_lbs", "activity_type", "distance_mi",
    "duration_min", "pace_min_mi", "avg_hr", "max_hr", "temp_f", "training_effect",
    "fished", "dove", "activity_count",
]

METERS_PER_MILE = 1609.34
GRAMS_PER_LB = 453.592


def _rows_as_dicts(ws: gspread.Worksheet) -> list[dict[str, str]]:
    values = ws.get_all_values()
    if not values:
        return []
    headers = values[0]
    return [dict(zip(headers, row)) for row in values[1:]]


def _float(s: Optional[str]) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _round(x: Optional[float], decimals: int) -> Any:
    return round(x, decimals) if x is not None else ""


def _bedtime(ms_str: Optional[str]) -> str:
    ms = _float(ms_str)
    if ms is None:
        return ""
    dt = datetime.datetime.utcfromtimestamp(ms / 1000)
    return dt.strftime("%H:%M")


def _pace(duration_min: Optional[float], distance_mi: Optional[float]) -> str:
    if not duration_min or not distance_mi:
        return ""
    pace = duration_min / distance_mi
    minutes = int(pace)
    seconds = round((pace - minutes) * 60)
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}"


def _pick_primary(activities: list[dict[str, str]]) -> Optional[dict[str, str]]:
    def is_fishing_or_diving(a: dict[str, str]) -> bool:
        t = (a.get("activity_type") or "").lower()
        return "fishing" in t or "diving" in t

    candidates = [a for a in activities if not is_fishing_or_diving(a)]
    if not candidates:
        return None

    running = [a for a in candidates if (a.get("activity_type") or "") in ("running", "treadmill_running")]
    pool = running if running else candidates
    return max(pool, key=lambda a: _float(a.get("total_timer_time")) or 0.0)


def build_daily_rows(sheet: gspread.Spreadsheet) -> list[dict[str, Any]]:
    activities = _rows_as_dicts(sheet.worksheet("Activities"))
    sleep = _rows_as_dicts(sheet.worksheet("Sleep"))
    weight = _rows_as_dicts(sheet.worksheet("Weight"))

    activities_by_date: dict[str, list[dict[str, str]]] = {}
    for a in activities:
        start = a.get("start_time_local") or ""
        if len(start) < 10:
            continue
        activities_by_date.setdefault(start[:10], []).append(a)

    sleep_by_date = {s["calendarDate"]: s for s in sleep if s.get("calendarDate")}
    weight_by_date = {w["calendarDate"]: w for w in weight if w.get("calendarDate")}

    all_dates = set(activities_by_date) | set(sleep_by_date) | set(weight_by_date)

    rows = []
    for date in sorted(all_dates, reverse=True):
        s = sleep_by_date.get(date, {})
        w = weight_by_date.get(date, {})
        day_activities = activities_by_date.get(date, [])
        primary = _pick_primary(day_activities)

        distance_mi = None
        duration_min = None
        if primary:
            dist_m = _float(primary.get("total_distance"))
            distance_mi = dist_m / METERS_PER_MILE if dist_m is not None else None
            timer_s = _float(primary.get("total_timer_time"))
            duration_min = timer_s / 60 if timer_s is not None else None

        temp_c = _float(primary.get("avg_temperature")) if primary else None
        temp_f = temp_c * 9 / 5 + 32 if temp_c is not None else None

        weight_g = _float(w.get("weight"))
        weight_lbs = weight_g / GRAMS_PER_LB if weight_g is not None else None

        sleep_s = _float(s.get("sleepTimeSeconds"))
        deep_s = _float(s.get("deepSleepSeconds"))
        rem_s = _float(s.get("remSleepSeconds"))

        fished = any("fishing" in (a.get("activity_type") or "").lower() for a in day_activities)
        dove = any("diving" in (a.get("activity_type") or "").lower() for a in day_activities)

        rows.append({
            "date": date,
            "resting_hr": s.get("restingHeartRate", ""),
            "sleep_hours": _round(sleep_s / 3600, 2) if sleep_s is not None else "",
            "deep_hours": _round(deep_s / 3600, 2) if deep_s is not None else "",
            "rem_hours": _round(rem_s / 3600, 2) if rem_s is not None else "",
            "bedtime": _bedtime(s.get("sleepStartTimestampLocal")),
            "sleep_stress": s.get("avgSleepStress", ""),
            "overnight_hrv": s.get("avgOvernightHrv", ""),
            "weight_lbs": _round(weight_lbs, 1),
            "activity_type": primary.get("activity_type", "") if primary else "",
            "distance_mi": _round(distance_mi, 2),
            "duration_min": _round(duration_min, 1),
            "pace_min_mi": _pace(duration_min, distance_mi),
            "avg_hr": primary.get("avg_heart_rate", "") if primary else "",
            "max_hr": primary.get("max_heart_rate", "") if primary else "",
            "temp_f": _round(temp_f, 1),
            "training_effect": primary.get("total_training_effect", "") if primary else "",
            "fished": "TRUE" if fished else "FALSE",
            "dove": "TRUE" if dove else "FALSE",
            "activity_count": len(day_activities),
        })

    return rows


def build_daily(sheet: gspread.Spreadsheet) -> int:
    rows = build_daily_rows(sheet)
    ws = sheets_writer.ensure_worksheet(sheet, "Daily")
    ws.clear()
    values = [COLUMNS] + [[row.get(c, "") for c in COLUMNS] for row in rows]
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    return len(rows)
