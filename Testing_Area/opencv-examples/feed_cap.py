import socket
import struct
import numpy as np
import cv2

HOST = "0.0.0.0"
PORT = 8000

def recv_all(sock, size):
    data = b""
    while len(data) < size:
        packet = sock.recv(size - len(data))
        if not packet:
            return None
        data += packet
    return data

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(1)

print(f"Listening on port {PORT}...")
conn, addr = server.accept()
print(f"Drone connected from {addr}")

try:
    while True:
        # Read 4-byte JPEG size
        size_data = recv_all(conn, 4)
        if size_data is None:
            print("Connection closed while reading frame size")
            break

        frame_size = struct.unpack("!I", size_data)[0]

        # Read JPEG bytes
        frame_data = recv_all(conn, frame_size)
        if frame_data is None:
            print("Connection closed while reading frame data")
            break

        # Decode JPEG into image
        jpg_array = np.frombuffer(frame_data, dtype=np.uint8)
        frame = cv2.imdecode(jpg_array, cv2.IMREAD_COLOR)

        if frame is None:
            print("Failed to decode JPEG frame")
            continue

        cv2.imshow("QDrone Live Feed", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    conn.close()
    server.close()
    cv2.destroyAllWindows()
