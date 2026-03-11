"""Email delivery strategy — sends the epub to a Kindle address via SMTP."""

from __future__ import annotations

import configparser
import json
import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from strategies import DeliveryStrategy, register

log = logging.getLogger("sz2kindle")

DATA_DIR = Path(os.environ.get("SZ2KINDLE_DATA_DIR", Path(__file__).parent.parent))
SENT_FILE = DATA_DIR / "sent.json"


def _load_sent() -> set[str]:
    if not SENT_FILE.exists():
        return set()
    try:
        return set(json.loads(SENT_FILE.read_text()))
    except (json.JSONDecodeError, TypeError):
        return set()


def _mark_sent(filename: str) -> None:
    sent = _load_sent()
    sent.add(filename)
    SENT_FILE.write_text(json.dumps(sorted(sent)))
    log.info("Marked %s as sent.", filename)


@register("email")
class EmailStrategy(DeliveryStrategy):
    def __init__(self, config: configparser.ConfigParser) -> None:
        self.smtp_cfg = config["smtp"]
        self.to_addr = config["kindle"]["to"]
        self.from_addr = self.smtp_cfg["from"]

    def already_delivered(self, filename: str) -> bool:
        return filename in _load_sent()

    def deliver(self, epub_path: Path) -> None:
        msg = MIMEMultipart()
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr
        msg["Subject"] = "SZ ePub"

        msg.attach(MIMEText("Attached is the latest Süddeutsche Zeitung ePub edition.", "plain"))

        attachment = MIMEBase("application", "epub+zip")
        attachment.set_payload(epub_path.read_bytes())
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", f'attachment; filename="{epub_path.name}"')
        msg.attach(attachment)

        log.info("Connecting to SMTP server %s:%s …", self.smtp_cfg["host"], self.smtp_cfg["port"])
        with smtplib.SMTP(self.smtp_cfg["host"], int(self.smtp_cfg["port"])) as server:
            server.starttls()
            server.login(self.smtp_cfg["username"], self.smtp_cfg["password"])
            server.sendmail(self.from_addr, self.to_addr, msg.as_string())

        log.info("Email sent to %s", self.to_addr)
        _mark_sent(epub_path.name)
