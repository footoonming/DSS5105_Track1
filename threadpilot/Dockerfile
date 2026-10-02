FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/threadpilot
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
COPY data/dictionary ./data/dictionary
COPY data/migrations ./data/migrations
COPY data/orders.csv data/production_log.csv data/workshops.csv ./data/
RUN mkdir -p backend/runtime data/raw data/snapshots && useradd -m app && chown -R app:app /srv/threadpilot
USER app
WORKDIR /srv/threadpilot/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
