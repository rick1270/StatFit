import datetime
from typing import Any, Optional

import gspread

from statfit import sheets_writer

COLUMNS = [
    "date", "resting_hr", "sleep_hours", "deep_hours", "rem_hours", "bedtime",
    "sleep_stress", "overnight_hrv", "weight_lbs", "body_fat_pct", "muscle_lbs",
    "activity_type", "distance_mi", "duration_min", "pace_min_mi", "cadence_spm",
    "avg_hr", "hr_first_half", "hr_second_half", "hr_drift", "max_hr", "temp_f",
    "training_effect", "fished", "dove", "activity_count",
    "bp_systolic", "bp_diastolic", "bp_pulse", "bp_readings",
]

WEEKLY_COLUMNS = [
    "week_start", "runs", "miles", "run_min", "avg_pace", "avg_hr", "long_run_mi",
    "avg_cadence_spm",
]

RUNNING_TYPES = ("running", "treadmill_running")

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
    if x is None:
        return ""
    return round(x, decimals) if decimals else round(x)


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

    running = [a for a in candidates if (a.get("activity_type") or "") in RUNNING_TYPES]
    pool = running if running else candidates
    return max(pool, key=lambda a: _float(a.get("total_timer_time")) or 0.0)


def _cadence_spm(activity: dict[str, str]) -> Optional[float]:
    """FIT running cadence counts one foot (strides/min); steps/min is double
    that, including the fractional part."""
    cadence = _float(activity.get("avg_running_cadence"))
    if cadence is None:
        return None
    return 2 * (cadence + (_float(activity.get("avg_fractional_cadence")) or 0.0))


def _mean(values: list[Optional[float]]) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def build_daily_rows(sheet: gspread.Spreadsheet) -> list[dict[str, Any]]:
    activities = _rows_as_dicts(sheet.worksheet("Activities"))
    sleep = _rows_as_dicts(sheet.worksheet("Sleep"))
    weight = _rows_as_dicts(sheet.worksheet("Weight"))
    try:
        blood_pressure = _rows_as_dicts(sheet.worksheet("BloodPressure"))
    except gspread.WorksheetNotFound:
        blood_pressure = []

    activities_by_date: dict[str, list[dict[str, str]]] = {}
    for a in activities:
        start = a.get("start_time_local") or ""
        if len(start) < 10:
            continue
        activities_by_date.setdefault(start[:10], []).append(a)

    sleep_by_date = {s["calendarDate"]: s for s in sleep if s.get("calendarDate")}
    weight_by_date = {w["calendarDate"]: w for w in weight if w.get("calendarDate")}

    bp_by_date: dict[str, list[dict[str, str]]] = {}
    for b in blood_pressure:
        if b.get("date"):
            bp_by_date.setdefault(b["date"], []).append(b)

    all_dates = set(activities_by_date) | set(sleep_by_date) | set(weight_by_date) | set(bp_by_date)

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
        muscle_g = _float(w.get("muscleMass"))
        muscle_lbs = muscle_g / GRAMS_PER_LB if muscle_g is not None else None

        hr_first = _float(primary.get("hr_first_half")) if primary else None
        hr_second = _float(primary.get("hr_second_half")) if primary else None
        hr_drift = hr_second - hr_first if hr_first is not None and hr_second is not None else None

        sleep_s = _float(s.get("sleepTimeSeconds"))
        deep_s = _float(s.get("deepSleepSeconds"))
        rem_s = _float(s.get("remSleepSeconds"))

        # Several readings a day get averaged (the usual home-BP practice).
        bp = bp_by_date.get(date, [])
        systolic = _mean([_float(b.get("systolic")) for b in bp])
        diastolic = _mean([_float(b.get("diastolic")) for b in bp])
        pulse = _mean([_float(b.get("pulse")) for b in bp])

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
            "body_fat_pct": w.get("bodyFat", ""),
            "muscle_lbs": _round(muscle_lbs, 1),
            "activity_type": primary.get("activity_type", "") if primary else "",
            "distance_mi": _round(distance_mi, 2),
            "duration_min": _round(duration_min, 1),
            "pace_min_mi": _pace(duration_min, distance_mi),
            "cadence_spm": _round(_cadence_spm(primary), 0) if primary else "",
            "avg_hr": primary.get("avg_heart_rate", "") if primary else "",
            "hr_first_half": _round(hr_first, 0),
            "hr_second_half": _round(hr_second, 0),
            "hr_drift": _round(hr_drift, 0),
            "max_hr": primary.get("max_heart_rate", "") if primary else "",
            "temp_f": _round(temp_f, 1),
            "training_effect": primary.get("total_training_effect", "") if primary else "",
            "fished": "TRUE" if fished else "FALSE",
            "dove": "TRUE" if dove else "FALSE",
            "activity_count": len(day_activities),
            "bp_systolic": _round(systolic, 0),
            "bp_diastolic": _round(diastolic, 0),
            "bp_pulse": _round(pulse, 0),
            "bp_readings": len(bp) if bp else "",
        })

    return rows


def build_weekly_rows(sheet: gspread.Spreadsheet) -> list[dict[str, Any]]:
    """One row per Monday-starting week, newest first, aggregating every run
    that week (not just each day's primary activity). Weeks with no runs are
    kept as zero rows so gaps show up in the trend."""
    runs_by_week: dict[datetime.date, list[dict[str, str]]] = {}
    for a in _rows_as_dicts(sheet.worksheet("Activities")):
        start = a.get("start_time_local") or ""
        if (a.get("activity_type") or "") not in RUNNING_TYPES or len(start) < 10:
            continue
        day = datetime.date.fromisoformat(start[:10])
        week = day - datetime.timedelta(days=day.weekday())
        runs_by_week.setdefault(week, []).append(a)
    if not runs_by_week:
        return []

    rows = []
    week = max(runs_by_week)
    while week >= min(runs_by_week):
        runs = runs_by_week.get(week, [])
        miles = sum((_float(r.get("total_distance")) or 0.0) for r in runs) / METERS_PER_MILE
        minutes = sum((_float(r.get("total_timer_time")) or 0.0) for r in runs) / 60

        # Time-weighted, so a long run counts for more than a short one.
        hr_pairs = [(_float(r.get("avg_heart_rate")), _float(r.get("total_timer_time"))) for r in runs]
        hr_pairs = [(hr, t) for hr, t in hr_pairs if hr is not None and t]
        hr_time = sum(t for _, t in hr_pairs)
        avg_hr = sum(hr * t for hr, t in hr_pairs) / hr_time if hr_time else None

        cad_pairs = [(_cadence_spm(r), _float(r.get("total_timer_time"))) for r in runs]
        cad_pairs = [(c, t) for c, t in cad_pairs if c is not None and t]
        cad_time = sum(t for _, t in cad_pairs)
        avg_cadence = sum(c * t for c, t in cad_pairs) / cad_time if cad_time else None

        long_run = max(((_float(r.get("total_distance")) or 0.0) for r in runs), default=0.0) / METERS_PER_MILE

        rows.append({
            "week_start": week.isoformat(),
            "runs": len(runs),
            "miles": _round(miles, 2),
            "run_min": _round(minutes, 1),
            "avg_pace": _pace(minutes, miles),
            "avg_hr": _round(avg_hr, 0),
            "long_run_mi": _round(long_run, 2) if runs else "",
            "avg_cadence_spm": _round(avg_cadence, 0),
        })
        week -= datetime.timedelta(days=7)

    return rows


def _rewrite_tab(sheet: gspread.Spreadsheet, title: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    ws = sheets_writer.ensure_worksheet(sheet, title)
    ws.clear()
    values = [columns] + [[row.get(c, "") for c in columns] for row in rows]
    ws.update(values=values, range_name="A1", value_input_option="RAW")


def build_daily(sheet: gspread.Spreadsheet) -> int:
    rows = build_daily_rows(sheet)
    _rewrite_tab(sheet, "Daily", COLUMNS, rows)
    return len(rows)


def build_weekly(sheet: gspread.Spreadsheet) -> int:
    rows = build_weekly_rows(sheet)
    _rewrite_tab(sheet, "Weekly", WEEKLY_COLUMNS, rows)
    return len(rows)
