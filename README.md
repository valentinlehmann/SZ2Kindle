# SZ2Kindle

I bought my grandfather a Kindle so he could read the *Süddeutsche Zeitung* without squinting at newsprint. The only missing piece: getting the daily ePub from his SZ-Plus subscription onto the device automatically.

This script does exactly that. It logs into [reader.sueddeutsche.de](https://reader.sueddeutsche.de), grabs the latest ePub edition, and emails it to a Kindle address. Run it once a day and the newspaper just shows up.

**Every line of code in this repository was written by [Claude Code](https://claude.ai/code)** — no manual edits. This doubles as a real-world case study of what AI-assisted development looks like end-to-end: from reverse-engineering the SZ authentication flow to debugging TLS fingerprinting issues to writing the Dockerfile.

## Setup

1. Clone the repo and copy the example config:
   ```bash
   cp config.ini.example config.ini
   ```

2. Fill in `config.ini` with your SZ-Plus credentials, SMTP server, and Kindle email address.

3. Run locally:
   ```bash
   pip install -r requirements.txt
   playwright install firefox
   python sz2kindle.py
   ```

   Or with Docker (runs daily at 6 AM Berlin time):
   ```bash
   docker compose up -d
   ```

## How it works

1. **Authenticate** — Reuses a cached session if still valid. Otherwise launches a headless Firefox via Playwright to log in through the Piano ID SSO iframe. Tokens are saved to `session.json` for reuse (~20 day lifetime).

2. **Find the latest edition** — Parses the reader page HTML to locate the newest "Süddeutsche Zeitung" ePub download link.

3. **Skip duplicates** — Checks `sent.json` to avoid re-sending an edition that was already delivered.

4. **Download** — Fetches the ePub via `curl` subprocess (the download endpoint uses TLS fingerprinting that rejects Python's HTTP libraries).

5. **Email** — Sends the ePub as an attachment to the configured Kindle address via SMTP.

## Configuration

| Section    | Key        | Description                          |
|------------|------------|--------------------------------------|
| `[sz]`     | `email`    | SZ-Plus login email                  |
| `[sz]`     | `password` | SZ-Plus login password               |
| `[sz]`     | `utp_token`| Optional: manual `__utp` cookie      |
| `[sz]`     | `tac_token`| Optional: manual `__tac` cookie      |
| `[smtp]`   | `host`     | SMTP server hostname                 |
| `[smtp]`   | `port`     | SMTP port (typically 587)            |
| `[smtp]`   | `username` | SMTP login username                  |
| `[smtp]`   | `password` | SMTP login password                  |
| `[smtp]`   | `from`     | Sender email address                 |
| `[kindle]` | `to`       | Kindle device email address          |

## Docker

The container uses cron to schedule runs — it idles between executions rather than running Python 24/7.

- **Default schedule**: daily at 06:00 (Berlin time)
- **Override**: set `SZ2KINDLE_CRON` in `compose.yaml` to any cron expression
- **Persistent data**: `session.json` and `sent.json` live in a Docker volume so sessions survive restarts

## Requirements

- Python 3.12+
- `curl` (system)
- Firefox (installed automatically by `playwright install firefox`)
- An active [SZ-Plus](https://www.sueddeutsche.de/szplus) subscription with ePaper access
