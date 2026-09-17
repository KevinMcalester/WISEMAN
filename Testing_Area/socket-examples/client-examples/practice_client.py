import socket

# creating socket_client
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect(('127.0.0.1', 8000)) # the server

# Send and Receive data
client_socket.send(b'Hello, client!') # expects a response
data = client_socket.recv(1024) # sends a response

print(f'Received: {data.decode()}')
client_socket.close()