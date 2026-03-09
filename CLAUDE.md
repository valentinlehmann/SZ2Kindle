# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SZ2Kindle downloads the daily "Süddeutsche Zeitung" ePub from `reader.sueddeutsche.de` and emails it to a Kindle address. Single-script Python tool (`sz2kindle.py`) with Docker support for scheduled daily runs.

## Running

**Local:**
```bash
pip install -r requirements.txt
playwright install firefox
python sz2kindle.py
```

**Docker:**
```bash
docker compose up -d
```

Configuration goes in `config.ini` (see `config.ini.example`). Sections: `[sz]` (credentials/tokens), `[smtp]` (mail server), `[kindle]` (recipient).

## Architecture

`sz2kindle.py` is the single entry point. Flow: authenticate → find latest epub URL → check if already sent → download → email → mark as sent.

### Key design decisions

- **TLS fingerprinting**: `reader.sueddeutsche.de` rejects Python's `requests`/`urllib3` TLS fingerprint. All HTTP requests use `subprocess` curl via `_curl_get()`.
- **Authentication**: Piano ID SSO (`auth.sueddeutsche.de`) with two cookies: `__utp` (identity JWT, ~20 day expiry) and `__tac` (access/entitlement JWT). Login automated via Playwright headless Firefox since the Piano login form lives in a JS-driven iframe that can't be replicated with plain HTTP.
- **Login fallback chain** in `get_tokens()`: saved session → manual tokens from config.ini → Playwright browser login.
- **Session validation**: `is_logged_in()` probes an actual epub download URL (not CSS classes, which are always `c-button--disabled` in raw HTML — JS removes them client-side).
- **Sent tracking**: `sent.json` records filenames of already-emailed epubs. Checked before downloading to avoid duplicate sends.
- **Data directory**: `SZ2KINDLE_DATA_DIR` env var controls where `config.ini`, `session.json`, and `sent.json` live. Defaults to the script's directory; set to `/data` in Docker.

### Persistent files (all gitignored)

- `config.ini` — user credentials and SMTP settings
- `session.json` — cached `__utp`/`__tac` tokens
- `sent.json` — list of already-sent epub filenames

## Docker

- `Dockerfile`: Python 3.13 slim + cron + curl + Playwright Firefox.
- `entrypoint.sh`: dumps env vars to `/etc/environment` for cron, runs script once on startup, then starts `cron -f`.
- `compose.yaml`: mounts `config.ini` read-only into `/data`, persists `session.json`/`sent.json` in a named volume (`sz2kindle-data`). Default schedule: daily 06:00 Berlin time, override via `SZ2KINDLE_CRON` env var.

## Dependencies

- `beautifulsoup4` — HTML parsing for epub link discovery
- `playwright` — headless browser login through Piano ID iframe
- `curl` (system) — all HTTP requests to reader.sueddeutsche.de
