#!/bin/sh
set -e

# Dump env vars so cron jobs can access them (cron starts with a bare env).
printenv | grep -Ev '^(no_proxy|HOME|PWD|SHLVL|_)=' > /etc/environment

# Build cron job that sources the env before running.
cat > /etc/cron.d/sz2kindle <<CRON
${SZ2KINDLE_CRON} root . /etc/environment; cd /app && /usr/local/bin/python sz2kindle.py >> /proc/1/fd/1 2>&1
CRON
chmod 0644 /etc/cron.d/sz2kindle

echo "Scheduled sz2kindle with cron: ${SZ2KINDLE_CRON}"

# Run once immediately on startup, then hand off to cron.
echo "Running initial check …"
cd /app && python sz2kindle.py || true

echo "Starting cron daemon …"
exec cron -f
