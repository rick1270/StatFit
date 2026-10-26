import datetime
import re
from typing import Any, Optional

import gspread

from statfit import sheets_writer
from statfit.daily import _float, _pace, _rows_as_dicts

TAB = "Splits"
FEET_PER_MILE = 5280

# One plan segment, e.g. "0.50-2.75 @ 4.2mph 1.0%".
SEGMENT_RE = re.compile(r"([\d.]+)\s*-\s*([\d.]+)\s*@\s*[\d.]+\s*mph\s+(-?[\d.]+)\s*%")


def build_row(activity_id: Any, activity_row: dict[str, Any], splits: list[dict[str, Any]]) -> dict[str, Any]:
    """One Splits row per run: partial-mile columns come before the mile_N
    columns, and are always present (blank if the leftover was dropped), so
    that upsert_rows — which appends unseen columns at the right — puts each
    new mile_N after the existing ones as longer runs show up."""
    full = [s for s in splits if s["distance_mi"] == 1.0]
    partial = splits[-1] if splits and splits[-1]["distance_mi"] != 1.0 else None
    row: dict[str, Any] = {
        "activity_id": activity_id,
        "date": str(activity_row.get("start_time_local") or "")[:10],
        "activity_type": activity_row.get("activity_type"),
        "distance_mi": round(sum(s["distance_mi"] for s in splits), 2),
        "elev_source": "watch" if any(s["elev_ft"] is not None for s in splits) else "",
        "partial_mi": "",
        "partial_pace": "",
        "partial_hr": "",
        "partial_elev_ft": "",
    }
    if partial:
        row.update(_split_fields("partial", partial))
        row["partial_mi"] = round(partial["distance_mi"], 2)
    for n, split in enumerate(full, start=1):
        row.update(_split_fields(f"mile_{n}", split))
    return row


def _split_fields(prefix: str, split: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_pace": _pace(split["elapsed_s"] / 60, split["distance_mi"]),
        f"{prefix}_hr": "" if split["hr"] is None else split["hr"],
        f"{prefix}_elev_ft": "" if split["elev_ft"] is None else split["elev_ft"],
    }


def _plan_date(value: Any) -> str:
    """Planned dates may be typed as real dates (a serial number unformatted)
    or as text."""
    if isinstance(value, (int, float)):
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(value))).isoformat()
    return str(value).strip()[:10]


def _plan_segments(plan: dict[str, Any]) -> list[tuple[float, float, float]]:
    """(start_mi, end_mi, incline_pct) per segment; falls back to one segment
    at avg_incline_pct over the whole distance if segments don't parse."""
    segments = [(float(a), float(b), float(pct)) for a, b, pct in SEGMENT_RE.findall(str(plan.get("segments") or ""))]
    if segments:
        return segments
    distance, incline = _float(str(plan.get("distance_mi", ""))), _float(str(plan.get("avg_incline_pct", "")))
    if distance and incline is not None:
        return [(0.0, distance, incline)]
    return []


def _planned_rise_ft(segments: list[tuple[float, float, float]], a: float, b: float) -> Optional[int]:
    """Net climb over [a, b] plan-miles, or None if the plan doesn't cover it."""
    if b > max(end for _, end, _ in segments) + 0.01:
        return None
    rise = sum(max(0.0, min(b, end) - max(a, start)) * pct / 100 for start, end, pct in segments)
    return round(rise * FEET_PER_MILE)


def fill_treadmill_elevation(sheet: gspread.Spreadsheet) -> int:
    """Treadmill runs record no elevation, but Claude-prescribed plans in the
    Planned tab give the incline per segment — net climb is distance ×
    incline. Matched by date when there's exactly one treadmill plan and one
    treadmill run that day; assumes the plan was run as written, with plan
    miles lining up with watch miles. Recomputed every rebuild, so a plan
    entered (or corrected) after the run still lands. Returns rows filled."""
    try:
        planned_ws = sheet.worksheet("Planned")
        splits_ws = sheet.worksheet(TAB)
    except gspread.WorksheetNotFound:
        return 0

    raw = planned_ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    plans_by_date: dict[str, list[dict[str, Any]]] = {}
    for values in raw[1:]:
        plan = dict(zip(raw[0], values))
        if "treadmill" in str(plan.get("type", "")).lower():
            plans_by_date.setdefault(_plan_date(plan.get("date")), []).append(plan)

    runs_by_date: dict[str, list[dict[str, str]]] = {}
    for run in _rows_as_dicts(splits_ws):
        if run.get("activity_type") == "treadmill_running":
            runs_by_date.setdefault(run["date"], []).append(run)

    updates = {}
    for date, plans in plans_by_date.items():
        runs = runs_by_date.get(date, [])
        if len(plans) != 1 or len(runs) != 1:
            if runs:
                print(f"  {date}: {len(plans)} treadmill plans vs {len(runs)} treadmill runs — not matching")
            continue
        segments = _plan_segments(plans[0])
        if not segments:
            continue
        run = runs[0]
        fields: dict[str, Any] = {"elev_source": "planned"}
        n = 1
        while f"mile_{n}_pace" in run and run[f"mile_{n}_pace"]:
            rise = _planned_rise_ft(segments, n - 1, n)
            fields[f"mile_{n}_elev_ft"] = "" if rise is None else rise
            n += 1
        partial = _float(run.get("partial_mi"))
        if partial:
            rise = _planned_rise_ft(segments, n - 1, n - 1 + partial)
            fields["partial_elev_ft"] = "" if rise is None else rise
        updates[run["activity_id"]] = fields

    if not updates:
        return 0
    return sheets_writer.update_columns(splits_ws, "activity_id", updates)
