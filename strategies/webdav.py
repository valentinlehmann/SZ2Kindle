"""WebDAV delivery strategy — uploads the epub to a WebDAV server."""

from __future__ import annotations

import configparser
import logging
import subprocess
from pathlib import Path

from strategies import DeliveryStrategy, register

log = logging.getLogger("sz2kindle")


@register("webdav")
class WebDAVStrategy(DeliveryStrategy):
    def __init__(self, config: configparser.ConfigParser) -> None:
        self.url = config.get("webdav", "url").rstrip("/")
        self.username = config.get("webdav", "username", fallback="")
        self.password = config.get("webdav", "password", fallback="")

    def _curl_auth_args(self) -> list[str]:
        if self.username and self.password:
            return ["-u", f"{self.username}:{self.password}"]
        return []

    def already_delivered(self, filename: str) -> bool:
        """Check if the file already exists on the WebDAV server via HEAD request."""
        remote_url = f"{self.url}/{filename}"
        cmd = [
            "curl", "-s", "-o", "/dev/null",
            "-w", "%{http_code}",
            "-I",  # HEAD request
            *self._curl_auth_args(),
            remote_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        status = result.stdout.strip()
        if status == "200":
            log.info("File %s already exists on WebDAV server.", filename)
            return True
        log.info("File %s not found on WebDAV server (HTTP %s).", filename, status)
        return False

    def deliver(self, epub_path: Path) -> None:
        """Upload the epub file to the WebDAV server via PUT request."""
        remote_url = f"{self.url}/{epub_path.name}"
        log.info("Uploading %s to %s …", epub_path.name, remote_url)
        cmd = [
            "curl", "-s",
            "-w", "%{http_code}",
            "-T", str(epub_path),
            *self._curl_auth_args(),
            remote_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        status = result.stdout.strip()[-3:]  # last 3 chars are the HTTP status
        if status in ("200", "201", "204"):
            log.info("Uploaded %s to WebDAV server (HTTP %s).", epub_path.name, status)
        else:
            log.error("WebDAV upload failed (HTTP %s): %s", status, result.stdout)
            raise RuntimeError(f"WebDAV upload failed with HTTP {status}")
