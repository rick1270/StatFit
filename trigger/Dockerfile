FROM python:3.12-slim

WORKDIR /app

# Flush print() immediately so Started/Skipped lines reach Cloud Logging per request.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 main:app
