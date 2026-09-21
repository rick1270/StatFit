import datetime
from pathlib import Path
from typing import Any

import fitparse

# We don't write raw per-record (per-second) streams to Sheets — that's
# thousands of rows per activity and Sheets isn't built for it. Session and
# lap summaries already carry the expanded metrics (running dynamics,
# training effect, power, respiration, etc.) that Strava's API doesn't
# expose. Revisit if a specific need for raw streams comes up.


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
    for lap_index, lap in enumerate(laps, start=1):
        lap["lap_index"] = lap_index

    return {"session": session, "laps": laps}
