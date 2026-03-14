"""
Mirror-Space Screen Receiver (Python)
Receives and displays screen broadcasts via UDP
"""

import sys
import time
import socket
import struct
from typing import Dict, Optional

import cv2
import numpy as np

from diff_encoder import DiffFrameDecoder


DEFAULT_PORT = 9999
MAX_PACKET_SIZE = 65507
RECEIVE_TIMEOUT = 5.0  # seconds


class UDPReceiver:
    """Handles UDP packet reception and reassembly"""
    
    def __init__(self, port: int):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Bind to all interfaces
        self.sock.bind(('0.0.0.0', port))
        
        # Set receive timeout
        self.sock.settimeout(RECEIVE_TIMEOUT)
        
        # Increase receive buffer size
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)
        
        print(f"UDP receiver initialized on port {port}")
    
    def receive_data(self) -> Optional[bytes]:
        """Receive and reassemble fragmented data"""
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
        """Close the socket"""
        self.sock.close()


def main():
    port = DEFAULT_PORT
    
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    
    print("=== Mirror-Space Screen Receiver (Python) ===")
    print(f"Listening on port: {port}")
    print("Press ESC or 'q' to quit...\n")
    
    # Initialize receiver
    try:
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
                    # Display frame
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
            if key == 27 or key == ord('q'):  # ESC or 'q'
                break
    
    except KeyboardInterrupt:
        print("\nStopping receiver...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        receiver.close()
        cv2.destroyAllWindows()
        print("Receiver stopped.")


if __name__ == "__main__":
    main()
