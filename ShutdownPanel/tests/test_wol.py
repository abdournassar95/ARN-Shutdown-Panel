import socket
import threading

from core import wol


def test_normalize_mac():
    assert wol.normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
    assert wol.normalize_mac("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"
    assert wol.normalize_mac("not a mac") is None
    assert wol.normalize_mac("") is None
    assert wol.normalize_mac("aa:bb:cc:dd:ee") is None


def test_magic_packet_structure():
    packet = wol.build_magic_packet("AA:BB:CC:DD:EE:FF")
    assert len(packet) == 102  # 6 * 0xFF + 16 * 6 MAC bytes
    assert packet[:6] == b"\xff" * 6
    assert packet[6:12] == bytes.fromhex("AABBCCDDEEFF")
    assert packet[-6:] == bytes.fromhex("AABBCCDDEEFF")


def test_wake_sends_udp_packet():
    """wake() must deliver the magic packet over UDP."""
    received = []
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.settimeout(3.0)

    def rx():
        try:
            data, addr = listener.recvfrom(2048)
            received.append(data)
        except socket.timeout:
            pass

    t = threading.Thread(target=rx, daemon=True)
    t.start()

    ok = wol.wake("AA:BB:CC:DD:EE:FF", broadcast="127.0.0.1", port=port, attempts=1)
    t.join(timeout=3.5)
    listener.close()

    assert ok is True
    assert len(received) == 1
    assert received[0] == wol.build_magic_packet("AA:BB:CC:DD:EE:FF")
