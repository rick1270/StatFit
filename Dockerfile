FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# omramin (OMRON connect -> Garmin Connect) gets its own venv: it pins a newer
# garminconnect than StatFit does.
COPY omramin-requirements.txt .
RUN python -m venv /opt/omramin && \
    /opt/omramin/bin/pip install --no-cache-dir -r omramin-requirements.txt

COPY statfit/ statfit/
COPY main.py build_daily.py cloud_run_entrypoint.py ./

CMD ["python", "cloud_run_entrypoint.py"]
