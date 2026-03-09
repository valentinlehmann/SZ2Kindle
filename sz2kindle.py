#!/usr/bin/env python3
"""Download the latest SZ ePub from reader.sueddeutsche.de and send it to a Kindle email."""

import configparser
import json
import logging
import os
import smtplib
import subprocess
import sys
import tempfile
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

READER_URL = "https://reader.sueddeutsche.de"

DATA_DIR = Path(os.environ.get("SZ2KINDLE_DATA_DIR", Path(__file__).parent))
SESSION_FILE = DATA_DIR / "session.json"
CONFIG_FILE = DATA_DIR / "config.ini"
SENT_FILE = DATA_DIR / "sent.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sz2kindle")


ENV_MAP = {
    "SZ_EMAIL":       ("sz", "email"),
    "SZ_PASSWORD":    ("sz", "password"),
    "SZ_UTP_TOKEN":   ("sz", "utp_token"),
    "SZ_TAC_TOKEN":   ("sz", "tac_token"),
    "SMTP_HOST":      ("smtp", "host"),
    "SMTP_PORT":      ("smtp", "port"),
    "SMTP_USERNAME":  ("smtp", "username"),
    "SMTP_PASSWORD":  ("smtp", "password"),
    "SMTP_FROM":      ("smtp", "from"),
    "KINDLE_TO":      ("kindle", "to"),
}


def load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
        log.info("Loaded config from %s", CONFIG_FILE)

    # Env vars override config.ini values.
    for env_key, (section, key) in ENV_MAP.items():
        value = os.environ.get(env_key, "").strip()
        if value:
            if not config.has_section(section):
                config.add_section(section)
            config.set(section, key, value)

    # Verify minimum required config is present.
    has_credentials = (
        config.get("sz", "email", fallback="") and config.get("sz", "password", fallback="")
    ) or (
        config.get("sz", "utp_token", fallback="") and config.get("sz", "tac_token", fallback="")
    )
    has_smtp = config.get("smtp", "host", fallback="") and config.get("kindle", "to", fallback="")

    if not has_credentials or not has_smtp:
        log.error(
            "Missing config. Provide config.ini or set env vars (SZ_EMAIL, SZ_PASSWORD, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, KINDLE_TO)."
        )
        sys.exit(1)

    return config


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

# The session stores the Piano __utp (identity) and __tac (access/entitlement)
# JWT cookies.  The reader.sueddeutsche.de download endpoint uses TLS
# fingerprinting, so we use curl (not requests) for actual downloads.


def save_session(tokens: dict[str, str]) -> None:
    SESSION_FILE.write_text(json.dumps(tokens))
    log.info("Session saved to %s", SESSION_FILE)


def load_session() -> dict[str, str] | None:
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text())
        if data.get("__utp") and data.get("__tac"):
            log.info("Loaded saved session from %s", SESSION_FILE)
            return data
    except (json.JSONDecodeError, KeyError):
        pass
    log.warning("No valid session file found.")
    return None


def _cookie_header(tokens: dict[str, str]) -> str:
    """Build a Cookie header string from token dict."""
    return "; ".join(f"{k}={v}" for k, v in tokens.items())


def _curl_get(url: str, tokens: dict[str, str], output_path: Path | None = None) -> subprocess.CompletedProcess:
    """GET a URL using curl with the given auth cookies."""
    cmd = [
        "curl", "-s", "-L",
        "-H", f"Cookie: {_cookie_header(tokens)}",
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:148.0) Gecko/20100101 Firefox/148.0",
        "-H", "Referer: https://reader.sueddeutsche.de/",
    ]
    if output_path:
        cmd += ["-o", str(output_path), "-w", "%{http_code} %{content_type}"]
    else:
        cmd += ["-w", "\n%{http_code} %{content_type}"]
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def is_logged_in(tokens: dict[str, str]) -> bool:
    """Check whether the tokens still grant access to epub downloads."""
    log.info("Checking if existing session is still valid …")

    # Fetch the main page to find an epub link.
    result = _curl_get(READER_URL, tokens)
    body = result.stdout
    status_line = body.strip().rsplit("\n", 1)[-1] if body else ""

    soup = BeautifulSoup(body, "html.parser")
    link = soup.select_one("a[href*='epub']")
    if not link:
        log.info("Could not find epub links on page.")
        return False

    href = link["href"]
    if href.startswith("./"):
        href = href[2:]
    probe_url = f"{READER_URL}/{href}" if not href.startswith("http") else href

    # Probe the download URL — check if we get epub content.
    with tempfile.NamedTemporaryFile(suffix=".probe", delete=True) as tmp:
        probe_path = Path(tmp.name)
    result = _curl_get(probe_url, tokens, probe_path)
    info = result.stdout.strip()  # "200 application/epub+zip" or "200 text/html"

    try:
        probe_path.unlink(missing_ok=True)
    except OSError:
        pass

    if "epub" in info or "octet-stream" in info:
        log.info("Session is valid (epub download accessible).")
        return True

    log.info("Session expired or invalid (%s).", info)
    return False


def login_via_browser(email: str, password: str) -> dict[str, str]:
    """Automate login via a headless browser using Playwright.

    Opens reader.sueddeutsche.de, clicks the Piano ID login button,
    fills in credentials, and waits for the __utp and __tac cookies.
    """
    from playwright.sync_api import sync_playwright

    log.info("Logging in via headless browser …")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(READER_URL, wait_until="networkidle")
        log.info("Loaded reader page, clicking login …")

        # Click the "SZ-Login" button which triggers window.login() / Piano modal.
        page.click("#js-login")

        # The Piano ID login form opens in an iframe.
        piano_frame = page.wait_for_selector(
            "iframe[src*='auth.sueddeutsche.de/id']", timeout=15000
        )
        frame = piano_frame.content_frame()

        # Fill in the email field.
        log.info("Filling in credentials …")
        email_input = frame.wait_for_selector("input[fieldloginemail], input[name='email'], input#login", timeout=10000)
        email_input.fill(email)

        # Fill in the password field.
        pw_input = frame.wait_for_selector("input[fieldloginpassword], input[type='password'], input#current-password", timeout=5000)
        pw_input.fill(password)

        # Click the login button inside the iframe.
        login_btn = frame.wait_for_selector("button[actionlogin], button[type='submit']", timeout=5000)
        login_btn.click()

        # Wait for the Piano SDK to set the __utp cookie after successful login.
        log.info("Waiting for authentication cookies …")
        utp_value = None
        tac_value = None

        for _ in range(60):  # up to 30 seconds
            page.wait_for_timeout(500)
            cookies = context.cookies()
            for c in cookies:
                if c["name"] == "__utp":
                    utp_value = c["value"]
                if c["name"] == "__tac":
                    tac_value = c["value"]
            if utp_value and tac_value:
                break

        browser.close()

    if not utp_value or not tac_value:
        log.error(
            "Login did not produce the expected cookies (__utp=%s, __tac=%s).",
            "found" if utp_value else "missing",
            "found" if tac_value else "missing",
        )
        sys.exit(1)

    log.info("Browser login successful.")
    return {"__utp": utp_value, "__tac": tac_value}


def get_tokens(config: configparser.ConfigParser) -> dict[str, str]:
    """Return a dict with __utp and __tac tokens, reusing saved ones if valid."""
    # Try saved session first.
    tokens = load_session()
    if tokens and is_logged_in(tokens):
        log.info("Reusing existing session.")
        return tokens

    # Check for manually provided tokens in config.
    utp = config.get("sz", "utp_token", fallback="").strip()
    tac = config.get("sz", "tac_token", fallback="").strip()
    if utp and tac:
        log.info("Using tokens from config.ini …")
        tokens = {"__utp": utp, "__tac": tac}
        if is_logged_in(tokens):
            save_session(tokens)
            return tokens
        log.warning("Provided tokens are expired or invalid.")

    # Log in via headless browser.
    email = config.get("sz", "email", fallback="").strip()
    password = config.get("sz", "password", fallback="").strip()
    if not email or not password:
        log.error("No valid session and no credentials in config.ini.")
        sys.exit(1)

    tokens = login_via_browser(email, password)
    save_session(tokens)
    return tokens


# ---------------------------------------------------------------------------
# ePub discovery & download
# ---------------------------------------------------------------------------


def find_latest_epub_url(tokens: dict[str, str]) -> str:
    """Find the download URL of the newest ePub of the daily 'Süddeutsche Zeitung'."""
    log.info("Looking for the latest ePub edition …")

    result = _curl_get(READER_URL, tokens)
    soup = BeautifulSoup(result.stdout, "html.parser")

    # The first c-issue--big whose product name is "Süddeutsche Zeitung" is the latest daily.
    for issue in soup.select("li.c-issue--big"):
        product = issue.select_one(".c-issue__product")
        if product and "Süddeutsche Zeitung" in product.get_text():
            link = issue.select_one("a[href*='epub']")
            if link:
                href = link["href"]
                if href.startswith("./"):
                    href = href[2:]
                url = f"{READER_URL}/{href}" if not href.startswith("http") else href
                date_el = issue.select_one(".c-issue__date")
                date_text = date_el.get_text(strip=True) if date_el else "unknown date"
                log.info("Found latest edition: %s — %s", date_text, url)
                return url

    # Fallback: first epub link on the page.
    link = soup.select_one("a[href*='epub']")
    if link:
        href = link["href"]
        if href.startswith("./"):
            href = href[2:]
        url = f"{READER_URL}/{href}" if not href.startswith("http") else href
        log.info("Found ePub link (fallback): %s", url)
        return url

    log.error("Could not find any ePub download link on the page.")
    sys.exit(1)


def download_epub(tokens: dict[str, str], url: str, dest_dir: Path) -> Path:
    """Download the ePub file using curl and return the local path."""
    # Derive filename from URL.
    qs = parse_qs(urlparse(url).query)
    path_param = qs.get("path", [""])[0]
    filename = Path(path_param).name if path_param else "sz_latest.epub"
    dest = dest_dir / filename

    log.info("Downloading ePub from %s …", url)
    result = _curl_get(url, tokens, dest)
    info = result.stdout.strip()

    if not dest.exists() or dest.stat().st_size == 0:
        log.error("Download failed: %s", info)
        sys.exit(1)

    if "epub" not in info and "octet-stream" not in info:
        # The downloaded file might be the unauthorized HTML page.
        log.error("Download did not return epub content: %s", info)
        sys.exit(1)

    size_mb = dest.stat().st_size / (1024 * 1024)
    log.info("Downloaded %s (%.2f MB)", dest.name, size_mb)
    return dest


# ---------------------------------------------------------------------------
# Sent tracking
# ---------------------------------------------------------------------------


def load_sent() -> set[str]:
    """Load the set of already-sent epub filenames."""
    if not SENT_FILE.exists():
        return set()
    try:
        return set(json.loads(SENT_FILE.read_text()))
    except (json.JSONDecodeError, TypeError):
        return set()


def mark_sent(filename: str) -> None:
    """Add a filename to the sent tracking file."""
    sent = load_sent()
    sent.add(filename)
    SENT_FILE.write_text(json.dumps(sorted(sent)))
    log.info("Marked %s as sent.", filename)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def send_email(epub_path: Path, config: configparser.ConfigParser) -> None:
    smtp_cfg = config["smtp"]
    to_addr = config["kindle"]["to"]
    from_addr = smtp_cfg["from"]

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = "SZ ePub"

    msg.attach(MIMEText("Attached is the latest Süddeutsche Zeitung ePub edition.", "plain"))

    attachment = MIMEBase("application", "epub+zip")
    attachment.set_payload(epub_path.read_bytes())
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", f'attachment; filename="{epub_path.name}"')
    msg.attach(attachment)

    log.info("Connecting to SMTP server %s:%s …", smtp_cfg["host"], smtp_cfg["port"])
    with smtplib.SMTP(smtp_cfg["host"], int(smtp_cfg["port"])) as server:
        server.starttls()
        server.login(smtp_cfg["username"], smtp_cfg["password"])
        server.sendmail(from_addr, to_addr, msg.as_string())

    log.info("Email sent to %s", to_addr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    config = load_config()
    tokens = get_tokens(config)

    epub_url = find_latest_epub_url(tokens)

    # Derive filename to check if already sent.
    qs = parse_qs(urlparse(epub_url).query)
    path_param = qs.get("path", [""])[0]
    filename = Path(path_param).name if path_param else "sz_latest.epub"

    if filename in load_sent():
        log.info("Already sent %s — nothing to do.", filename)
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        epub_path = download_epub(tokens, epub_url, Path(tmpdir))
        send_email(epub_path, config)

    mark_sent(filename)
    log.info("Done.")


if __name__ == "__main__":
    main()
