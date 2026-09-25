FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY statfit/ statfit/
COPY main.py build_daily.py cloud_run_entrypoint.py ./

CMD ["python", "cloud_run_entrypoint.py"]
