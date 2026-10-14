import json
import socket
import time

from core.discovery import BROADCAST_MAGIC, DISCOVERY_PORT, UDPBeacon, UDPListener


def test_beacon_initialization_and_lifecycle():
    beacon = UDPBeacon("TestHost", 8080, interval=0.2)
    assert beacon.server_name == "TestHost"
    assert beacon.server_port == 8080
    assert beacon._running is False

    beacon.start()
    assert beacon._running is True
    assert beacon._thread is not None and beacon._thread.is_alive()

    # Calling start again does not create a second thread
    th = beacon._thread
    beacon.start()
    assert beacon._thread is th

    beacon.stop()
    assert beacon._running is False
    assert not beacon._thread.is_alive()


def test_listener_lifecycle():
    discovered = []
    listener = UDPListener(on_discovered=lambda m: discovered.append(m))
    assert listener._running is False

    listener.start()
    time.sleep(0.2)
    listener.stop()
    assert listener._running is False


def test_listener_filters_foreign_payload():
    discovered = []
    listener = UDPListener(on_discovered=lambda m: discovered.append(m))
    
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        listener.start()
        time.sleep(0.1)

        # Send invalid JSON
        test_sock.sendto(b"not json", ("127.0.0.1", DISCOVERY_PORT))
        # Send JSON without magic
        test_sock.sendto(json.dumps({"app": "OtherApp"}).encode("utf-8"), ("127.0.0.1", DISCOVERY_PORT))
        # Send valid payload
        valid_payload = json.dumps({
            "app": BROADCAST_MAGIC,
            "name": "TargetPC",
            "port": 9090
        }).encode("utf-8")
        test_sock.sendto(valid_payload, ("127.0.0.1", DISCOVERY_PORT))

        time.sleep(0.4)
    finally:
        listener.stop()
        test_sock.close()

    target = [d for d in discovered if d.get("name") == "TargetPC"]
    assert len(target) >= 1
    found = target[0]
    assert found["name"] == "TargetPC"
    assert found["port"] == 9090
    assert "ip" in found
