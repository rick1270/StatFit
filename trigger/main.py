"""HTTP endpoint that starts the statfit-sync Cloud Run Job on demand.

Called by Tasker on Rick's phone when Garmin Connect posts an "activity ready
to view" notification. The job's own Cloud Scheduler trigger (every 6 hours)
stays in place as a fallback for missed notifications and for sleep/weight data.

Auth is a shared secret in the X-StatFit-Token header (from Secret Manager),
since getting a Google OAuth token from Tasker is impractical. This service
then starts the job as its own service account.
"""
import datetime
import hmac
import os

import google.auth
import google.auth.transport.requests
import requests
from flask import Flask, jsonify, request

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "statfit-509421")
REGION = os.environ.get("JOB_REGION", "us-central1")
JOB = os.environ.get("JOB_NAME", "statfit-sync")
TRIGGER_TOKEN = os.environ["TRIGGER_TOKEN"]
# Skip if the job started this recently, so a burst of notifications (several
# activities syncing from the watch at once) becomes a single run.
DEBOUNCE_SECONDS = int(os.environ.get("DEBOUNCE_SECONDS", "120"))

JOB_URL = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs/{JOB}"

app = Flask(__name__)
_credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])


def _auth_headers() -> dict[str, str]:
    if not _credentials.valid:
        _credentials.refresh(google.auth.transport.requests.Request())
    return {"Authorization": f"Bearer {_credentials.token}"}


def _blocking_execution() -> str | None:
    """Name of an execution that should suppress a new run: one still running
    (two concurrent runs would race on sync_state.json in GCS and could append
    duplicate rows to the Sheet), or one started within DEBOUNCE_SECONDS."""
    resp = requests.get(f"{JOB_URL}/executions", headers=_auth_headers(),
                        params={"pageSize": 5}, timeout=15)
    resp.raise_for_status()
    now = datetime.datetime.now(datetime.timezone.utc)
    for execution in resp.json().get("executions", []):
        if "completionTime" not in execution:
            return execution["name"]
        created = datetime.datetime.fromisoformat(execution["createTime"].replace("Z", "+00:00"))
        if (now - created).total_seconds() < DEBOUNCE_SECONDS:
            return execution["name"]
    return None


@app.post("/")
def trigger():
    token = request.headers.get("X-StatFit-Token", "")
    if not hmac.compare_digest(token, TRIGGER_TOKEN):
        return jsonify(status="unauthorized"), 401

    blocking = _blocking_execution()
    if blocking:
        print(f"Skipped: {blocking} is running or started within {DEBOUNCE_SECONDS}s")
        return jsonify(status="skipped", execution=blocking.rsplit("/", 1)[-1])

    resp = requests.post(f"{JOB_URL}:run", headers=_auth_headers(), json={}, timeout=15)
    resp.raise_for_status()
    execution = resp.json().get("metadata", {}).get("name", "")
    print(f"Started {execution} (source: {request.headers.get('X-StatFit-Source', 'unknown')})")
    return jsonify(status="started", execution=execution.rsplit("/", 1)[-1])
