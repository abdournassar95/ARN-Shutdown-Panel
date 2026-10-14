"""
Wake-on-LAN: builds and sends magic packets to power on machines remotely.
"""

import re
import socket
import struct
from typing import Optional

MAC_PATTERN = re.compile(r"^\s*([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\s*$")
DEFAULT_PORT = 9


def normalize_mac(mac: str) -> Optional[str]:
    """Validates a MAC address and returns it normalized (AA:BB:CC:DD:EE:FF) or None."""
    if not mac or not MAC_PATTERN.match(mac):
        return None
    return ":".join(mac.strip().replace("-", ":").split(":")).upper()


def build_magic_packet(mac: str) -> bytes:
    """Builds the 102-byte WoL magic packet: 6x 0xFF + 16x MAC."""
    normalized = normalize_mac(mac)
    if not normalized:
        raise ValueError(f"Invalid MAC address: {mac!r}")
    mac_bytes = bytes.fromhex(normalized.replace(":", ""))
    return b"\xff" * 6 + mac_bytes * 16


def wake(
    mac: str,
    broadcast: str = "255.255.255.255",
    port: int = DEFAULT_PORT,
    attempts: int = 3,
) -> bool:
    """
    Sends the magic packet via UDP broadcast.
    Returns True if at least one datagram was sent successfully.
    """
    packet = build_magic_packet(mac)
    sent = 0
    for _ in range(max(1, attempts)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.settimeout(1.0)
                sock.sendto(packet, (broadcast, port))
                sent += 1
        except OSError:
            continue
    return sent > 0
