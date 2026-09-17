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
server.bind((HOST, PORT))
server.listen(1)

print(f"Listening on port {PORT}...")
conn, addr = server.accept()
print(f"Drone connected from {addr}")

try:
    while True:
        header = recv_all(conn, 16)
        if header is None:
            print("Connection closed while reading header")
            break

        width, height, channels, data_size = struct.unpack("!IIII", header)

        frame_data = recv_all(conn, data_size)
        if frame_data is None:
            print("Connection closed while reading frame")
            break

        frame = np.frombuffer(frame_data, dtype=np.uint8).reshape((height, width, channels))

        cv2.imshow("QDrone Live Feed", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
finally:
    conn.close()
    server.close()
    cv2.destroyAllWindows()
