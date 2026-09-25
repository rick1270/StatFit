from google.cloud import storage

from statfit import config

STATE_PREFIX = "state/"


def download_state(bucket_name: str) -> None:
    """Pull the last run's state/ contents (sync watermark, cached Garmin
    session) down from GCS before syncing. A Cloud Run Job's local disk
    doesn't persist between executions, so this stands in for that."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    for blob in client.list_blobs(bucket, prefix=STATE_PREFIX):
        rel = blob.name[len(STATE_PREFIX):]
        if not rel or blob.name.endswith("/"):
            continue
        dest = config.STATE_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(dest))


def upload_state(bucket_name: str) -> None:
    """Push state/ back up to GCS so the next execution can resume from it."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    for path in config.STATE_DIR.rglob("*"):
        if path.is_file():
            rel = path.relative_to(config.STATE_DIR).as_posix()
            bucket.blob(f"{STATE_PREFIX}{rel}").upload_from_filename(str(path))
