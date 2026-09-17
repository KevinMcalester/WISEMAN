import socket
import threading
import hmac

client_data = {}

def _hashed_client_id(client_address):
    addr_str = f"{client_address[0]}:{client_address[1]}"
    return hmac.new(addr_str.encode(), client_data).hexdigest()

def handel_client(conn,addr):
    print(f"[NEW CONNECTION] {addr} connected]")
    client_hash = _hashed_client_id(addr)

    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break

            message = data.decode().strip()
            conn.sendall(f"Stored under hash: {client_hash[:8]}...".encode())
    except Exception as e:
        print(e)

    finally:
        conn.close()
        print(f"{addr} disconnected")
        client_data.pop(client_hash, None)

def start_server(host = '127.0.0.1', port = 8000):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((host,port))
    server.listen(5)

    print(f"[LISTENING] {host}:{port}")

    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target=handel_client, args=(conn, addr))
        thread.start()

if __name__ == "__main__":
    start_server()