# SZ2Kindle

I bought my grandfather a Kindle so he could read the *Süddeutsche Zeitung* without squinting at newsprint. The only missing piece: getting the daily ePub from his SZ-Plus subscription onto the device automatically.

This script does exactly that. It logs into [reader.sueddeutsche.de](https://reader.sueddeutsche.de), grabs the latest ePub edition, and emails it to a Kindle address. Run it once a day and the newspaper just shows up.

**Every line of code in this repository was written by [Claude Code](https://claude.ai/code)** — no manual edits. This doubles as a real-world case study of what AI-assisted development looks like end-to-end: from reverse-engineering the SZ authentication flow to debugging TLS fingerprinting issues to writing the Dockerfile.

## Setup

### Docker (recommended)

Fill in the environment variables in `compose.yaml` and run:

```bash
docker compose up -d
```

Alternatively, mount a `config.ini` instead of using env vars (see below).

### Local

```bash
cp config.ini.example config.ini
# Fill in config.ini
pip install -r requirements.txt
playwright install chromium
python sz2kindle.py
```

## How it works

1. **Authenticate** — Reuses a cached session if still valid. Otherwise launches headless Chromium via Playwright to log in through the Piano ID SSO iframe. Tokens are saved to `session.json` for reuse (~20 day lifetime).

2. **Find the latest edition** — Parses the reader page HTML to locate the newest "Süddeutsche Zeitung" ePub download link.

3. **Skip duplicates** — Checks `sent.json` to avoid re-sending an edition that was already delivered.

4. **Download** — Fetches the ePub via `curl` subprocess (the download endpoint uses TLS fingerprinting that rejects Python's HTTP libraries).

5. **Email** — Sends the ePub as an attachment to the configured Kindle address via SMTP.

## Configuration

Configure via environment variables, `config.ini`, or both. Env vars take precedence.

| Env var          | config.ini equivalent   | Description                          |
|------------------|-------------------------|--------------------------------------|
| `SZ_EMAIL`       | `[sz] email`            | SZ-Plus login email                  |
| `SZ_PASSWORD`    | `[sz] password`         | SZ-Plus login password               |
| `SZ_UTP_TOKEN`   | `[sz] utp_token`        | Optional: manual `__utp` cookie      |
| `SZ_TAC_TOKEN`   | `[sz] tac_token`        | Optional: manual `__tac` cookie      |
| `SMTP_HOST`      | `[smtp] host`           | SMTP server hostname                 |
| `SMTP_PORT`      | `[smtp] port`           | SMTP port (typically 587)            |
| `SMTP_USERNAME`  | `[smtp] username`       | SMTP login username                  |
| `SMTP_PASSWORD`  | `[smtp] password`       | SMTP login password                  |
| `SMTP_FROM`      | `[smtp] from`           | Sender email address                 |
| `KINDLE_TO`      | `[kindle] to`           | Kindle device email address          |

## Docker

The container uses cron to schedule runs — it idles between executions rather than running Python 24/7.

- **Default schedule**: daily at 06:00 (Berlin time)
- **Override**: set `SZ2KINDLE_CRON` in `compose.yaml` to any cron expression
- **Persistent data**: `session.json` and `sent.json` live in a Docker volume so sessions survive restarts
- **Config**: use env vars in `compose.yaml`, or uncomment the volume mount to use a `config.ini` file instead

## Requirements

- Python 3.12+
- `curl` (system)
- Chromium (installed automatically by `playwright install chromium`)
- An active [SZ-Plus](https://www.sueddeutsche.de/szplus) subscription with ePaper access
