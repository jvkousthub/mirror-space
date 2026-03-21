"""
Mirror-Space Screen Broadcaster (Python)
Captures screen and broadcasts via UDP to multiple receivers using diff-frame encoding.

Multi-Viewer Mode:
  - Receivers register by sending JOIN packets to the control port.
  - Broadcaster sends frames to ALL registered receivers.
  - Stale clients (no heartbeat in 10s) are automatically pruned.
"""

import sys
import time
import socket
import struct
import threading
from typing import Dict, Tuple

import mss
import numpy as np
import cv2

from diff_encoder import DiffFrameEncoder


DEFAULT_PORT = 9999
CONTROL_PORT_OFFSET = 1  # Control port = data port + 1
MAX_PACKET_SIZE = 65507  # Max UDP packet size
TARGET_FPS = 30
FRAME_INTERVAL = 1.0 / TARGET_FPS
SHOW_HEATMAP = True  # Set to False to disable heatmap overlay
CLIENT_TIMEOUT = 10.0  # Seconds before a silent client is pruned


# ---------------------------------------------------------------------------
# Client Manager – thread-safe registry of connected receivers
# ---------------------------------------------------------------------------

class ClientInfo:
    """Stores metadata about a connected receiver."""
    def __init__(self, addr: Tuple[str, int], name: str):
        self.addr = addr          # (ip, data_port) – where to send frames
        self.name = name
        self.joined_at = time.time()
        self.last_heartbeat = time.time()


class ClientManager:
    """Thread-safe registry of connected viewers."""

    def __init__(self, timeout: float = CLIENT_TIMEOUT):
        self._clients: Dict[Tuple[str, int], ClientInfo] = {}
        self._lock = threading.Lock()
        self._timeout = timeout

    # -- mutations ----------------------------------------------------------

    def add_client(self, addr: Tuple[str, int], name: str) -> bool:
        """Register a new client.  Returns True if it was genuinely new."""
        with self._lock:
            is_new = addr not in self._clients
            self._clients[addr] = ClientInfo(addr, name)
            if is_new:
                print(f"\n[+] Client joined: {name} ({addr[0]}:{addr[1]})")
            return is_new

    def heartbeat(self, addr: Tuple[str, int]):
        """Refresh a client's last-seen timestamp."""
        with self._lock:
            if addr in self._clients:
                self._clients[addr].last_heartbeat = time.time()

    def remove_client(self, addr: Tuple[str, int]):
        """Explicitly remove a client (LEAVE message)."""
        with self._lock:
            info = self._clients.pop(addr, None)
            if info:
                print(f"\n[-] Client left: {info.name} ({addr[0]}:{addr[1]})")

    def prune_stale(self):
        """Remove clients that haven't sent a heartbeat within the timeout."""
        now = time.time()
        with self._lock:
            stale = [
                addr for addr, info in self._clients.items()
                if now - info.last_heartbeat > self._timeout
            ]
            for addr in stale:
                info = self._clients.pop(addr)
                print(f"\n[!] Client timed out: {info.name} ({addr[0]}:{addr[1]})")

    # -- queries ------------------------------------------------------------

    def get_active_addrs(self):
        """Return a snapshot list of (ip, port) tuples for all active clients."""
        with self._lock:
            return list(self._clients.keys())

    def count(self) -> int:
        with self._lock:
            return len(self._clients)

    def summary(self) -> str:
        """One-line summary for the console dashboard."""
        with self._lock:
            if not self._clients:
                return "0 viewers connected"
            names = [c.name for c in self._clients.values()]
            return f"{len(names)} viewer(s): {', '.join(names)}"


# ---------------------------------------------------------------------------
# UDP Broadcaster – sends frames to every registered client
# ---------------------------------------------------------------------------

class UDPBroadcaster:
    """Handles UDP packet transmission with fragmentation to multiple targets."""

    def __init__(self, port: int):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Increase send buffer size
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
        print(f"UDP broadcaster initialized on data port {port}")

    def send_data(self, data: bytes, targets: list) -> int:
        """Send data with automatic fragmentation to all targets.
        Returns the number of clients that were successfully sent to."""
        if not targets:
            return 0

        offset = 0
        packet_index = 0
        total_packets = (len(data) + MAX_PACKET_SIZE - 9) // (MAX_PACKET_SIZE - 8)

        # Pre-build all fragment packets
        packets = []
        while offset < len(data):
            chunk_size = min(MAX_PACKET_SIZE - 8, len(data) - offset)
            packet = struct.pack('<II', total_packets, packet_index)
            packet += data[offset:offset + chunk_size]
            packets.append(packet)
            offset += chunk_size
            packet_index += 1

        # Send every packet to every target
        success_count = 0
        for target in targets:
            try:
                for i, packet in enumerate(packets):
                    self.sock.sendto(packet, target)
                    if i < len(packets) - 1:
                        time.sleep(0.0001)  # 100µs inter-packet gap
                success_count += 1
            except Exception as e:
                print(f"Send failed to {target}: {e}")

        return success_count

    def close(self):
        """Close the socket."""
        self.sock.close()


# ---------------------------------------------------------------------------
# Screen Capture
# ---------------------------------------------------------------------------

class ScreenCapture:
    """Captures screen using mss library."""

    def __init__(self):
        self.sct = mss.mss()
        self.monitor = self.sct.monitors[1]  # Primary monitor
        print(f"Screen capture initialized: {self.monitor['width']}x{self.monitor['height']}")

    def capture_frame(self) -> np.ndarray:
        """Capture current screen frame."""
        screenshot = self.sct.grab(self.monitor)
        frame = np.array(screenshot)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        return frame

    def get_dimensions(self) -> Tuple[int, int]:
        """Get screen dimensions."""
        return self.monitor['width'], self.monitor['height']

    def close(self):
        """Clean up resources."""
        self.sct.close()


# ---------------------------------------------------------------------------
# Heatmap overlay (unchanged)
# ---------------------------------------------------------------------------

def create_heatmap_overlay(frame: np.ndarray, changed_blocks, block_size: int) -> np.ndarray:
    """Create a heatmap overlay showing changed blocks."""
    overlay = frame.copy()
    heatmap = np.zeros((frame.shape[0], frame.shape[1]), dtype=np.uint8)

    for x, y, w, h in changed_blocks:
        heatmap[y:y+h, x:x+w] = 255

    heatmap_colored = cv2.applyColorMap(heatmap, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(frame, 0.7, heatmap_colored, 0.3, 0)

    height, width = frame.shape[:2]
    for y_line in range(0, height, block_size):
        cv2.line(overlay, (0, y_line), (width, y_line), (100, 100, 100), 1)
    for x_line in range(0, width, block_size):
        cv2.line(overlay, (x_line, 0), (x_line, height), (100, 100, 100), 1)

    for x, y, w, h in changed_blocks:
        cv2.rectangle(overlay, (x, y), (x+w, y+h), (0, 255, 0), 2)

    text = f"Changed Blocks: {len(changed_blocks)}"
    cv2.putText(overlay, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                1, (0, 255, 0), 2, cv2.LINE_AA)

    return overlay


# ---------------------------------------------------------------------------
# Control listener – runs in a background thread
# ---------------------------------------------------------------------------

def control_listener(client_manager: ClientManager, control_port: int, data_port: int, stop_event: threading.Event):
    """Listen for JOIN / HEARTBEAT / LEAVE messages from receivers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', control_port))
    sock.settimeout(1.0)  # So we can check the stop event periodically
    print(f"Control listener started on port {control_port}")

    while not stop_event.is_set():
        try:
            raw, addr = sock.recvfrom(1024)
        except socket.timeout:
            # Periodically prune stale clients
            client_manager.prune_stale()
            continue
        except Exception as e:
            print(f"Control socket error: {e}")
            continue

        msg = raw.rstrip(b'\x00').decode('utf-8', errors='ignore')

        if msg.startswith("MSCP:JOIN:"):
            client_name = msg[len("MSCP:JOIN:"):]
            # The client will receive data on its *sending* IP but on the data port
            client_data_addr = (addr[0], data_port)
            client_manager.add_client(client_data_addr, client_name)

            # Send WELCOME back
            welcome = f"MSCP:WELCOME:{data_port}\x00".encode()
            sock.sendto(welcome, addr)

        elif msg == "MSCP:HEARTBEAT":
            client_data_addr = (addr[0], data_port)
            client_manager.heartbeat(client_data_addr)

        elif msg == "MSCP:LEAVE":
            client_data_addr = (addr[0], data_port)
            client_manager.remove_client(client_data_addr)

        # Prune stale clients on every message too
        client_manager.prune_stale()

    sock.close()
    print("Control listener stopped.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    port = DEFAULT_PORT

    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    control_port = port + CONTROL_PORT_OFFSET

    print("=== Mirror-Space Screen Broadcaster (Multi-Viewer) ===")
    print(f"Data port    : {port}")
    print(f"Control port : {control_port}")
    print(f"Target FPS   : {TARGET_FPS}")
    print(f"Heatmap      : {'Enabled' if SHOW_HEATMAP else 'Disabled'}")
    print("Press Ctrl+C to stop...")
    if SHOW_HEATMAP:
        print("Press 'h' to toggle heatmap, 'q' to quit\n")
    else:
        print()

    # Initialize components
    capture = None
    broadcaster = None
    stop_event = threading.Event()

    try:
        capture = ScreenCapture()
        encoder = DiffFrameEncoder(block_size=32, threshold=10)
        broadcaster = UDPBroadcaster(port)
        client_manager = ClientManager(timeout=CLIENT_TIMEOUT)

        # Start control listener in background
        ctrl_thread = threading.Thread(
            target=control_listener,
            args=(client_manager, control_port, port, stop_event),
            daemon=True,
        )
        ctrl_thread.start()

        # Create heatmap window if enabled
        heatmap_enabled = SHOW_HEATMAP
        if SHOW_HEATMAP:
            cv2.namedWindow("Broadcaster Heatmap", cv2.WINDOW_NORMAL)

        # Broadcasting loop
        frame_number = 0
        if SHOW_HEATMAP:
            cv2.destroyAllWindows()
        fps_counter = 0
        fps_start_time = time.time()

        print("Waiting for viewers to connect...\n")

        while True:
            frame_start = time.time()

            # Capture screen
            frame = capture.capture_frame()

            # Encode frame
            encoded_data = encoder.encode(frame, frame_number)

            # Show heatmap if enabled
            if heatmap_enabled:
                changed_blocks = encoder.get_changed_block_positions()
                heatmap = create_heatmap_overlay(frame, changed_blocks, encoder.block_size)

                # Resize for display if too large
                display_height = 720
                if heatmap.shape[0] > display_height:
                    scale = display_height / heatmap.shape[0]
                    display_width = int(heatmap.shape[1] * scale)
                    heatmap = cv2.resize(heatmap, (display_width, display_height))

                cv2.imshow("Broadcaster Heatmap", heatmap)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('h'):
                    heatmap_enabled = not heatmap_enabled
                    if not heatmap_enabled:
                        cv2.destroyWindow("Broadcaster Heatmap")
                    else:
                        cv2.namedWindow("Broadcaster Heatmap", cv2.WINDOW_NORMAL)

            # Send to all registered clients
            targets = client_manager.get_active_addrs()
            if targets:
                broadcaster.send_data(encoded_data, targets)

            frame_number += 1
            fps_counter += 1

            # Dashboard update every second
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                actual_fps = fps_counter / elapsed
                viewer_info = client_manager.summary()
                print(f"FPS: {actual_fps:.1f} | {viewer_info}")
                fps_counter = 0
                fps_start_time = time.time()

            # Frame rate limiting
            frame_time = time.time() - frame_start
            sleep_time = FRAME_INTERVAL - frame_time
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nStopping broadcaster...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        stop_event.set()
        if capture:
            capture.close()
        if broadcaster:
            broadcaster.close()
        cv2.destroyAllWindows()
        print("Broadcaster stopped.")


if __name__ == "__main__":
    main()
