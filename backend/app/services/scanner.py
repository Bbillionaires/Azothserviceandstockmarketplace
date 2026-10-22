"""Malware scanning hook for uploads.

``none``   records the file as *not scanned*. Acceptable for local
           development only; production must configure a scanner.
``clamav`` streams the file to a clamd daemon (``CLAMD_HOST``/``CLAMD_PORT``)
           using the INSTREAM protocol.
"""

import os
import socket
import struct
from pathlib import Path

from app.core.config import get_settings
from app.models import ScanStatus


def scan_file(path: Path) -> ScanStatus:
    if get_settings().malware_scanner != "clamav":
        return ScanStatus.not_scanned
    try:
        return _clamd_instream(path)
    except OSError:
        return ScanStatus.error


def _clamd_instream(path: Path) -> ScanStatus:
    host = os.environ.get("CLAMD_HOST", "127.0.0.1")
    port = int(os.environ.get("CLAMD_PORT", "3310"))
    with socket.create_connection((host, port), timeout=60) as sock, path.open("rb") as fh:
        sock.sendall(b"zINSTREAM\0")
        while chunk := fh.read(64 * 1024):
            sock.sendall(struct.pack("!L", len(chunk)) + chunk)
        sock.sendall(struct.pack("!L", 0))
        reply = sock.recv(4096).decode(errors="replace")
    if reply.rstrip("\0").endswith("OK"):
        return ScanStatus.clean
    if "FOUND" in reply:
        return ScanStatus.infected
    return ScanStatus.error
