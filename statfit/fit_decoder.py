import bisect
import datetime
from pathlib import Path
from typing import Any

import fitparse

# We don't write raw per-record (per-second) streams to Sheets — that's
# thousands of rows per activity and Sheets isn't built for it. Session and
# lap summaries already carry the expanded metrics (running dynamics,
# training effect, power, respiration, etc.) that Strava's API doesn't
# expose. Revisit if a specific need for raw streams comes up. Records are
# only read to derive a few summary numbers (see _hr_halves, _mile_splits).

# A gap between HR samples longer than this is treated as a pause rather than
# held at the last reading.
MAX_SAMPLE_GAP_S = 60

METERS_PER_MILE = 1609.34
FEET_PER_METER = 3.28084
# A leftover after the last full mile shorter than this is GPS/stop-button
# noise, not a real partial mile.
MIN_PARTIAL_MI = 0.05


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    if isinstance(value, (list, tuple)):
        if all(v is None for v in value):
            return None
        return ",".join("" if v is None else str(_serialize(v)) for v in value)
    return value


def _message_to_dict(message: fitparse.records.DataMessage) -> dict[str, Any]:
    serialized = ((field, _serialize(value)) for field, value in message.get_values().items())
    return {field: value for field, value in serialized if value is not None}


def _hr_halves(fit_file: fitparse.FitFile) -> tuple[int, int] | None:
    """Time-weighted average HR over the first and second half of the
    activity, split at the midpoint between the first and last HR sample.
    Shows cardiac drift ("HR crept up 15 bpm") on steady efforts."""
    points = []
    for m in fit_file.get_messages("record"):
        values = m.get_values()
        if values.get("timestamp") is not None and values.get("heart_rate") is not None:
            points.append((values["timestamp"], values["heart_rate"]))
    if len(points) < 2:
        return None

    midpoint = points[0][0] + (points[-1][0] - points[0][0]) / 2
    weighted = [0.0, 0.0]
    seconds = [0.0, 0.0]
    for (t, hr), (t_next, _) in zip(points, points[1:]):
        if (t_next - t).total_seconds() > MAX_SAMPLE_GAP_S:
            continue
        for half, (start, end) in enumerate(((t, min(t_next, midpoint)), (max(t, midpoint), t_next))):
            d = (end - start).total_seconds()
            if d > 0:
                weighted[half] += hr * d
                seconds[half] += d
    if not all(seconds):
        return None
    return round(weighted[0] / seconds[0]), round(weighted[1] / seconds[1])


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation of y at x over ascending xs, clamped at the ends.
    bisect_left picks the first sample reaching x, so a pause sitting exactly
    on a boundary counts toward the later segment."""
    i = bisect.bisect_left(xs, x)
    if i == 0:
        return ys[0]
    if i == len(xs):
        return ys[-1]
    x0, x1 = xs[i - 1], xs[i]
    if x1 == x0:
        return ys[i]
    return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - x0) / (x1 - x0)


def _mile_splits(fit_file: fitparse.FitFile, indoor: bool, total_distance: float | None) -> list[dict[str, Any]]:
    """Per-mile splits from the record stream: elapsed seconds (pauses
    included), time-weighted HR, and net elevation change in feet, with the
    exact crossing of each mile interpolated between samples. A final partial
    mile is included if at least MIN_PARTIAL_MI long.

    Indoor (treadmill) runs: altitude is ignored — the barometer there
    measures nothing useful — and record distances (the watch's wrist-based
    estimate) are scaled to the session total, which Garmin replaces with the
    treadmill's distance when it's entered at save time."""
    dists: list[float] = []
    secs: list[float] = []
    alt_dists: list[float] = []
    alts: list[float] = []
    hr_points = []
    t0 = None
    for m in fit_file.get_messages("record"):
        values = m.get_values()
        t, d = values.get("timestamp"), values.get("distance")
        if t is None:
            continue
        if t0 is None:
            t0 = t
        s = (t - t0).total_seconds()
        if values.get("heart_rate") is not None:
            hr_points.append((s, values["heart_rate"]))
        # Distance is cumulative; drop samples that would run it backwards.
        if d is None or (dists and d < dists[-1]):
            continue
        dists.append(d)
        secs.append(s)
        alt = values.get("enhanced_altitude", values.get("altitude"))
        if not indoor and alt is not None:
            alt_dists.append(d)
            alts.append(alt)
    if len(dists) < 2 or dists[-1] <= 0:
        return []
    if indoor and total_distance:
        scale = total_distance / dists[-1]
        dists = [d * scale for d in dists]

    total_mi = dists[-1] / METERS_PER_MILE
    full_miles = int(total_mi)
    edges = [float(k) for k in range(full_miles + 1)]
    if total_mi - full_miles >= MIN_PARTIAL_MI:
        edges.append(total_mi)

    def hr_between(start: float, end: float) -> int | None:
        weighted = seconds = 0.0
        for (s, hr), (s_next, _) in zip(hr_points, hr_points[1:]):
            if s_next - s > MAX_SAMPLE_GAP_S:
                continue
            overlap = min(s_next, end) - max(s, start)
            if overlap > 0:
                weighted += hr * overlap
                seconds += overlap
        return round(weighted / seconds) if seconds else None

    splits = []
    for a, b in zip(edges, edges[1:]):
        start = _interp(dists, secs, a * METERS_PER_MILE) if a else 0.0
        end = _interp(dists, secs, b * METERS_PER_MILE)
        elev_ft = None
        if alts:
            rise = _interp(alt_dists, alts, b * METERS_PER_MILE) - _interp(alt_dists, alts, a * METERS_PER_MILE)
            elev_ft = round(rise * FEET_PER_METER)
        splits.append({
            "distance_mi": b - a,
            "elapsed_s": end - start,
            "hr": hr_between(start, end),
            "elev_ft": elev_ft,
        })
    return splits


def decode_fit(fit_path: Path) -> dict[str, Any]:
    """Decode a FIT file into an activity-level session summary plus a list
    of lap summaries. Field sets vary by device/activity type — we return
    whatever fields the file actually contains rather than a fixed schema."""
    fit_file = fitparse.FitFile(str(fit_path))
    fit_file.parse()

    sessions = [_message_to_dict(m) for m in fit_file.get_messages("session")]
    laps = [_message_to_dict(m) for m in fit_file.get_messages("lap")]

    if not sessions:
        raise ValueError(f"No session message found in {fit_path}")

    session = sessions[0]
    halves = _hr_halves(fit_file)
    if halves:
        session["hr_first_half"], session["hr_second_half"] = halves
    for lap_index, lap in enumerate(laps, start=1):
        lap["lap_index"] = lap_index

    splits = []
    if session.get("sport") == "running":
        splits = _mile_splits(fit_file, indoor=session.get("sub_sport") == "treadmill",
                              total_distance=session.get("total_distance"))

    return {"session": session, "laps": laps, "splits": splits}
