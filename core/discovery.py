import socket
import threading
import time
import json
from typing import Optional, Callable, Dict, Any

from core.app_logger import get_logger

DISCOVERY_PORT = 44444
BROADCAST_MAGIC = "ShutdownPanel"

class UDPBeacon:
    """Broadcasts server presence on the local network via UDP."""
    
    def __init__(self, server_name: str, server_port: int, interval: float = 3.0):
        self.server_name = server_name
        self.server_port = server_port
        self.interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _broadcast_loop(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # Try to allow port reuse just in case
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
            
            payload = json.dumps({
                "app": BROADCAST_MAGIC,
                "name": self.server_name,
                "port": self.server_port
            }).encode("utf-8")
            
            while self._running:
                try:
                    s.sendto(payload, ("<broadcast>", DISCOVERY_PORT))
                except Exception as e:
                    get_logger().debug(f"UDP Beacon broadcast failed: {e}")
                
                time.sleep(self.interval)

class UDPListener:
    """Listens for Server broadcasts on the local network."""
    
    def __init__(self, on_discovered: Callable[[Dict[str, Any]], None]):
        self.on_discovered = on_discovered
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

    def start(self):
        if self._running:
            return
        self._running = True
        
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
            
        try:
            self._sock.bind(("", DISCOVERY_PORT))
            self._sock.settimeout(1.0)
        except Exception as e:
            get_logger().error(f"UDP Listener failed to bind port {DISCOVERY_PORT}: {e}")
            self._running = False
            return
            
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _listen_loop(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(1024)
                ip = addr[0]
                try:
                    msg = json.loads(data.decode("utf-8"))
                    if msg.get("app") == BROADCAST_MAGIC:
                        msg["ip"] = ip
                        self.on_discovered(msg)
                except json.JSONDecodeError:
                    pass
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    get_logger().debug(f"UDP Listener error: {e}")
                break
