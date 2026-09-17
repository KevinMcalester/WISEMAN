import socket

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind(("0.0.0.0", 8000))
server_socket.listen(1)

print("listening on port 8000...")

conn, addr = server_socket.accept()
print("connected by", addr)

data = conn.recv(1024)
print("received:", data.decode())

conn.sendall(b"ack from windows server")

conn.close()
server_socket.close()