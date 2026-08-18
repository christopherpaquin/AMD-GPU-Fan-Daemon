"""Minimal stdlib-only sd_notify client (no python-systemd dependency).

Talks to systemd over the AF_UNIX datagram socket named in $NOTIFY_SOCKET.
Silently does nothing when that variable is unset (e.g. running outside
systemd, or under pytest) - notification is a courtesy to the supervisor,
not something the daemon's own correctness depends on.
"""

from __future__ import annotations

import os
import socket


def notify(state: str) -> None:
    """Send a single sd_notify state string, e.g. "READY=1" or "WATCHDOG=1"."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]

    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(address)
        sock.sendall(state.encode())
