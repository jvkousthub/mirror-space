"""
Mirror-Space Screen Receiver (Python)
Receives and displays screen broadcasts via UDP.

Multi-Viewer Mode:
  - Sends a JOIN message to the broadcaster's control port on startup.
  - Sends periodic HEARTBEAT messages so the broadcaster knows we're alive.
  - Sends a LEAVE message on graceful shutdown.
"""

import sys
import time
import socket
import struct
import threading
import platform
from typing import Dict, Optional

import cv2
import numpy as np

from diff_encoder import DiffFrameDecoder


DEFAULT_PORT = 9999
CONTROL_PORT_OFFSET = 1  # Control port = data port + 1
MAX_PACKET_SIZE = 65507
RECEIVE_TIMEOUT = 5.0  # seconds
HEARTBEAT_INTERVAL = 3.0  # seconds


# ---------------------------------------------------------------------------
# Heartbeat sender – runs in a background thread
# ---------------------------------------------------------------------------

def heartbeat_loop(broadcaster_ip: str, control_port: int, stop_event: threading.Event):
    """Periodically send HEARTBEAT messages to the broadcaster."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg = b"MSCP:HEARTBEAT\x00"

    while not stop_event.is_set():
        try:
            sock.sendto(msg, (broadcaster_ip, control_port))
        except Exception as e:
            print(f"Heartbeat send failed: {e}")
        stop_event.wait(HEARTBEAT_INTERVAL)

    sock.close()


# ---------------------------------------------------------------------------
# UDP Receiver
# ---------------------------------------------------------------------------

class UDPReceiver:
    """Handles UDP packet reception and reassembly."""

    def __init__(self, port: int):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Allow address reuse so multiple receivers can run on same machine
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind to all interfaces
        self.sock.bind(('0.0.0.0', port))

        # Set receive timeout
        self.sock.settimeout(RECEIVE_TIMEOUT)

        # Increase receive buffer size
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)

        print(f"UDP receiver listening on port {port}")

    def receive_data(self) -> Optional[bytes]:
        """Receive and reassemble fragmented data."""
        packets: Dict[int, bytes] = {}
        total_packets = 0
        start_time = time.time()

        while True:
            # Check timeout
            if time.time() - start_time > 1.0 and packets:
                break  # Partial frame, return what we have

            try:
                data, addr = self.sock.recvfrom(MAX_PACKET_SIZE)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Receive error: {e}")
                return None

            if len(data) < 8:
                continue  # Too small for header

            # Parse packet header
            total, index = struct.unpack('<II', data[:8])
            payload = data[8:]

            if total_packets == 0:
                total_packets = total

            # Store packet
            packets[index] = payload

            # Check if we have all packets
            if len(packets) == total_packets:
                break

        if not packets:
            return None

        # Reassemble data in order
        result = bytearray()
        for i in range(total_packets):
            if i in packets:
                result.extend(packets[i])
            else:
                print(f"Missing packet {i} of {total_packets}")

        return bytes(result) if result else None

    def close(self):
        """Close the socket."""
        self.sock.close()


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def send_join(broadcaster_ip: str, control_port: int, client_name: str) -> bool:
    """Send a JOIN message to the broadcaster. Returns True on WELCOME ack."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)

    join_msg = f"MSCP:JOIN:{client_name}\x00".encode()
    try:
        sock.sendto(join_msg, (broadcaster_ip, control_port))
        # Wait for WELCOME
        data, _ = sock.recvfrom(1024)
        msg = data.rstrip(b'\x00').decode('utf-8', errors='ignore')
        if msg.startswith("MSCP:WELCOME"):
            print(f"Registered with broadcaster at {broadcaster_ip}")
            return True
    except socket.timeout:
        print("No WELCOME received (broadcaster may not be running yet). Continuing anyway...")
        return True  # Still try to receive – broadcaster might start later
    except Exception as e:
        print(f"JOIN failed: {e}")
    finally:
        sock.close()
    return True


def send_leave(broadcaster_ip: str, control_port: int):
    """Send a LEAVE message to the broadcaster (best-effort)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"MSCP:LEAVE\x00", (broadcaster_ip, control_port))
        sock.close()
    except Exception:
        pass  # Best-effort


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    broadcaster_ip = "127.0.0.1"
    port = DEFAULT_PORT
    client_name = platform.node()  # Default name = hostname

    # Parse arguments:  receiver.py <broadcaster_ip> [port] [--name NAME]
    args = sys.argv[1:]
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            client_name = args[i + 1]
            i += 2
        else:
            positional.append(args[i])
            i += 1

    if len(positional) >= 1:
        broadcaster_ip = positional[0]
    if len(positional) >= 2:
        port = int(positional[1])

    control_port = port + CONTROL_PORT_OFFSET

    print("=== Mirror-Space Screen Receiver (Multi-Viewer) ===")
    print(f"Broadcaster  : {broadcaster_ip}")
    print(f"Data port    : {port}")
    print(f"Control port : {control_port}")
    print(f"Client name  : {client_name}")
    print("Press ESC or 'q' to quit...\n")

    stop_event = threading.Event()
    receiver = None

    try:
        # Register with broadcaster
        send_join(broadcaster_ip, control_port, client_name)

        # Start heartbeat thread
        hb_thread = threading.Thread(
            target=heartbeat_loop,
            args=(broadcaster_ip, control_port, stop_event),
            daemon=True,
        )
        hb_thread.start()

        # Initialize receiver
        receiver = UDPReceiver(port)
        decoder = DiffFrameDecoder()

        # Create display window
        cv2.namedWindow("Mirror-Space Receiver", cv2.WINDOW_NORMAL)

        # Receiving loop
        frames_received = 0
        fps_start_time = time.time()

        print("Waiting for frames...\n")

        while True:
            # Receive data
            received_data = receiver.receive_data()

            if received_data:
                # Decode frame
                frame = decoder.decode(received_data)

                if frame is not None:
                    cv2.imshow("Mirror-Space Receiver", frame)
                    frames_received += 1

            # Calculate FPS
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                actual_fps = frames_received / elapsed
                print(f"Receive FPS: {actual_fps:.1f}")
                frames_received = 0
                fps_start_time = time.time()

            # Check for exit (ESC or 'q')
            key = cv2.waitKey(1) & 0xFF
            if key == 27 or key == ord('q'):
                break

    except KeyboardInterrupt:
        print("\nStopping receiver...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        stop_event.set()
        # Send LEAVE (best-effort)
        send_leave(broadcaster_ip, control_port)
        if receiver:
            receiver.close()
        cv2.destroyAllWindows()
        print("Receiver stopped.")


if __name__ == "__main__":
    main()
