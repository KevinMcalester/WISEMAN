import socket
import struct
import traceback
import time
import cv2
import numpy as np


HOST = "0.0.0.0"
PORT = 8000
BACKLOG = 5

ACCEPT_TIMEOUT = 5.0
CLIENT_TIMEOUT = 10.0

HEADER_SIZE = 8
MAX_FRAME_SIZE = 10 * 1024 * 1024   # 10 MB safety limit

WINDOW_NAME = "Quanser Drone Feed"
SHOW_VIDEO = True
PRINT_FRAME_EVERY = 30

# Diagnostic client markers
HANDSHAKE_PREFIX = b"DRONE_HELLO"
HANDSHAKE_REPLY = b"SERVER_HELLO: connection test acknowledged"


def log(msg: str) -> None:
    print(f"[SERVER] {msg}")


def describe_socket_error(err: OSError) -> str:
    if isinstance(err, TimeoutError):
        return "Operation timed out."
    if isinstance(err, ConnectionRefusedError):
        return "Connection was refused."
    if isinstance(err, ConnectionResetError):
        return "Connection was reset by the client."
    if isinstance(err, PermissionError):
        return "Permission denied. Firewall, antivirus, or OS policy may be blocking this socket."

    winerror = getattr(err, "winerror", None)
    errno_val = getattr(err, "errno", None)

    # Windows
    if winerror == 10013:
        return "Windows blocked the socket operation. Firewall, antivirus, permissions, or antivirus may be interfering."
    if winerror == 10048:
        return "Port is already in use by another process."
    if winerror == 10049:
        return "The bind address is not valid on this machine."
    if winerror == 10060:
        return "A connection attempt timed out."
    if winerror == 10061:
        return "No service accepted the connection."
    if winerror == 10064:
        return "Host is down or unreachable."
    if winerror == 10065:
        return "No route to host."

    # Linux / POSIX
    if errno_val == 98:
        return "Port is already in use."
    if errno_val == 99:
        return "Cannot bind to that address on this machine."
    if errno_val == 104:
        return "Connection reset by peer."
    if errno_val == 110:
        return "Connection timed out."
    if errno_val == 111:
        return "Connection refused."
    if errno_val == 113:
        return "No route to host."

    return f"Unhandled socket error: {err}"


def print_server_startup_notes() -> None:
    log("Starting unified Quanser server...")
    log(f"Bind host           : {HOST}")
    log(f"Bind port           : {PORT}")
    log("Supported client modes:")
    log("  1. Diagnostic handshake client")
    log("     Expected text prefix: DRONE_HELLO")
    log("  2. Video stream client")
    log("     Expected protocol   : [8-byte frame size][JPEG frame bytes]")
    log(f"Header size         : {HEADER_SIZE} bytes")
    log(f"Max frame size      : {MAX_FRAME_SIZE} bytes")
    log("If the drone cannot connect, likely causes include:")
    log("  1. Wrong laptop IP in the drone code")
    log("  2. Windows firewall blocking inbound TCP on port 8000")
    log("  3. Server not running when the drone tries to connect")
    log("  4. Laptop and drone are on different interfaces")
    log("  5. Another process already using port 8000")
    log("-" * 70)


def recv_exact(sock: socket.socket, num_bytes: int) -> bytes | None:
    """
    Receive exactly num_bytes.
    Returns None if timeout happens or the peer closes the connection.
    """
    data = bytearray()

    while len(data) < num_bytes:
        try:
            chunk = sock.recv(num_bytes - len(data))
        except socket.timeout:
            return None

        if not chunk:
            return None

        data.extend(chunk)

    return bytes(data)


def recv_until_quiet(sock: socket.socket, initial_bytes: bytes, quiet_timeout: float = 0.5, max_bytes: int = 4096) -> bytes:
    """
    Used for handshake text clients.
    Starts with initial bytes already received, then keeps reading until
    the socket is quiet for a short period or max_bytes is reached.
    """
    data = bytearray(initial_bytes)

    original_timeout = sock.gettimeout()
    sock.settimeout(quiet_timeout)

    try:
        while len(data) < max_bytes:
            try:
                chunk = sock.recv(min(1024, max_bytes - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            except socket.timeout:
                break
    finally:
        sock.settimeout(original_timeout)

    return bytes(data)


def looks_like_handshake(first_bytes: bytes) -> bool:
    """
    Decide whether this client is the diagnostic text client.
    """
    return first_bytes.startswith(HANDSHAKE_PREFIX)


def handle_handshake_client(client_socket: socket.socket, client_addr, first_chunk: bytes) -> None:
    client_ip, client_port = client_addr
    log(f"Client mode detected : DIAGNOSTIC HANDSHAKE from {client_ip}:{client_port}")

    try:
        full_message_bytes = recv_until_quiet(client_socket, first_chunk)
        try:
            full_message = full_message_bytes.decode("utf-8", errors="replace")
        except Exception:
            full_message = repr(full_message_bytes)

        log(f"Handshake payload    : {full_message!r}")

        try:
            client_socket.sendall(HANDSHAKE_REPLY)
            log(f"Sent reply           : {HANDSHAKE_REPLY.decode('utf-8', errors='replace')!r}")
        except OSError as err:
            log("Failed to send handshake reply.")
            log(describe_socket_error(err))
            log(f"Raw error            : {repr(err)}")
            return

        log("Handshake session completed successfully.")

    except OSError as err:
        log("Socket error while handling handshake client.")
        log(describe_socket_error(err))
        log(f"Raw error            : {repr(err)}")
    except Exception as err:
        log("Unexpected error while handling handshake client.")
        log(f"Type                 : {type(err).__name__}")
        log(f"Message              : {err}")
        traceback.print_exc()


def handle_video_client(client_socket: socket.socket, client_addr, first_header_bytes: bytes) -> None:
    client_ip, client_port = client_addr
    log(f"Client mode detected : VIDEO STREAM from {client_ip}:{client_port}")

    frame_counter = 0
    start_time = time.time()

    try:
        if len(first_header_bytes) != HEADER_SIZE:
            log(f"Invalid first header length: got {len(first_header_bytes)}, expected {HEADER_SIZE}")
            return

        if SHOW_VIDEO:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

        current_header = first_header_bytes

        while True:
            frame_size = struct.unpack("!Q", current_header)[0]

            if frame_size <= 0:
                log(f"Invalid frame size received: {frame_size}")
                break

            if frame_size > MAX_FRAME_SIZE:
                log(f"Frame too large ({frame_size} bytes). Closing connection for safety.")
                break

            frame_data = recv_exact(client_socket, frame_size)
            if frame_data is None:
                log("Client disconnected while sending frame payload.")
                break

            np_frame = np.frombuffer(frame_data, dtype=np.uint8)
            frame = cv2.imdecode(np_frame, cv2.IMREAD_COLOR)

            if frame is None:
                log("Failed to decode incoming JPEG frame.")
            else:
                frame_counter += 1

                if frame_counter % PRINT_FRAME_EVERY == 0:
                    elapsed = max(time.time() - start_time, 1e-6)
                    fps = frame_counter / elapsed
                    h, w = frame.shape[:2]
                    log(f"Received frame #{frame_counter} | size={frame_size} bytes | resolution={w}x{h} | avg_fps={fps:.2f}")

                if SHOW_VIDEO:
                    cv2.imshow(WINDOW_NAME, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        log("User pressed 'q'. Closing video client connection.")
                        break

            current_header = recv_exact(client_socket, HEADER_SIZE)
            if current_header is None:
                log("Client disconnected or next frame header was not received.")
                break

    except OSError as err:
        log("Socket error while handling video client.")
        log(describe_socket_error(err))
        log(f"Raw error            : {repr(err)}")
    except Exception as err:
        log("Unexpected error while handling video client.")
        log(f"Type                 : {type(err).__name__}")
        log(f"Message              : {err}")
        traceback.print_exc()
    finally:
        if SHOW_VIDEO:
            cv2.destroyAllWindows()

        total_time = max(time.time() - start_time, 1e-6)
        if frame_counter > 0:
            log(f"Session summary      : {frame_counter} frames in {total_time:.2f}s ({frame_counter / total_time:.2f} avg FPS)")


def handle_client(client_socket: socket.socket, client_addr) -> None:
    client_ip, client_port = client_addr
    log(f"Accepted connection from {client_ip}:{client_port}")

    try:
        client_socket.settimeout(CLIENT_TIMEOUT)

        try:
            local_ip, local_port = client_socket.getsockname()
            peer_ip, peer_port = client_socket.getpeername()
            log(f"Local endpoint       : {local_ip}:{local_port}")
            log(f"Remote endpoint      : {peer_ip}:{peer_port}")
        except OSError as err:
            log("Connected, but failed to inspect socket endpoints.")
            log(describe_socket_error(err))
            log(f"Raw error            : {repr(err)}")

        first_chunk = recv_exact(client_socket, HEADER_SIZE)
        if first_chunk is None:
            log("Client connected but sent no data.")
            return

        # Decide which protocol this client is using.
        if looks_like_handshake(first_chunk):
            handle_handshake_client(client_socket, client_addr, first_chunk)
        else:
            handle_video_client(client_socket, client_addr, first_chunk)

    finally:
        try:
            client_socket.close()
            log("Closed client socket.")
        except Exception:
            log("Failed to close client socket cleanly.")

        log("-" * 70)


def main() -> None:
    print_server_startup_notes()

    server_socket = None

    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        log("Socket created successfully.")

        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        log("Enabled SO_REUSEADDR.")

        try:
            server_socket.bind((HOST, PORT))
            log(f"Bind successful on {HOST}:{PORT}")
        except OSError as err:
            log("Bind failed.")
            log(describe_socket_error(err))
            log(f"Raw error            : {repr(err)}")
            return

        try:
            server_socket.listen(BACKLOG)
            log(f"Server is now listening with backlog={BACKLOG}")
        except OSError as err:
            log("Listen failed.")
            log(describe_socket_error(err))
            log(f"Raw error            : {repr(err)}")
            return

        server_socket.settimeout(ACCEPT_TIMEOUT)
        log(f"Waiting for drone connection... accept timeout={ACCEPT_TIMEOUT}s")

        while True:
            try:
                client_socket, client_addr = server_socket.accept()
                handle_client(client_socket, client_addr)
            except socket.timeout:
                log("No incoming connection arrived during the timeout window.")
            except OSError as err:
                log("Accept failed.")
                log(describe_socket_error(err))
                log(f"Raw error            : {repr(err)}")

    except KeyboardInterrupt:
        log("Server stopped by user.")
    except Exception as err:
        log("Unexpected fatal server error.")
        log(f"Type                 : {type(err).__name__}")
        log(f"Message              : {err}")
        traceback.print_exc()
    finally:
        if server_socket is not None:
            try:
                server_socket.close()
                log("Server socket closed.")
            except Exception:
                log("Failed to close server socket cleanly.")

        if SHOW_VIDEO:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
