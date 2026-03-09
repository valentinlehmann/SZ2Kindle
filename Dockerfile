FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends cron curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps firefox

COPY sz2kindle.py .

# Cron schedule: every day at 6:00 AM (container timezone).
# Override with SZ2KINDLE_CRON env var.
ENV SZ2KINDLE_CRON="0 6 * * *"
ENV SZ2KINDLE_DATA_DIR=/data

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
