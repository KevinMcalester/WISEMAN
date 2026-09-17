import socket
import struct
import time
import traceback
import cv2


HOST = "192.168.2.168"   # replace with your laptop IP
PORT = 8000
CONNECT_TIMEOUT = 5.0
SEND_DELAY = 0.03
JPEG_QUALITY = 80

# choose mode here
MODE = "video"          # "handshake" or "video"

HANDSHAKE_MESSAGE = "DRONE_HELLO: testing connection"
RECV_REPLY_SIZE = 1024


def log(msg: str) -> None:
    print(f"[DRONE] {msg}")


def describe_socket_error(err: OSError) -> str:
    if isinstance(err, TimeoutError):
        return "Operation timed out."
    if isinstance(err, ConnectionRefusedError):
        return "Connection was refused. The server is not listening, the port is wrong, or a firewall rejected it."
    if isinstance(err, ConnectionResetError):
        return "Connection was reset after being established."
    if isinstance(err, PermissionError):
        return "Permission denied. Local policy, permissions, or security software may be blocking the socket."

    errno_val = getattr(err, "errno", None)

    if errno_val == 101:
        return "Network is unreachable. The drone does not currently have a usable route to the target network."
    if errno_val == 110:
        return "Connection attempt timed out. Packets likely did not reach the server or the reply never came back."
    if errno_val == 111:
        return "Connection refused. The target IP was reached, but nothing accepted the connection on that port."
    if errno_val == 113:
        return "No route to host. The IP may be wrong, the host may be offline, or the link is broken."

    return f"Unhandled socket error: {err}"


def print_client_startup_notes() -> None:
    log("Starting Quanser drone client...")
    log(f"Target host     : {HOST}")
    log(f"Target port     : {PORT}")
    log(f"Connect timeout : {CONNECT_TIMEOUT} seconds")
    log(f"Mode            : {MODE}")

    if MODE == "handshake":
        log("Protocol        : text handshake")
    elif MODE == "video":
        log("Protocol        : [8-byte frame size][JPEG frame bytes]")
    else:
        log("Protocol        : UNKNOWN MODE")

    log("-" * 60)


def connect_to_server():
    sock = None

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)

        log("Attempting to connect to laptop...")
        sock.connect((HOST, PORT))
        log("Connected to laptop successfully.")

        try:
            local_ip, local_port = sock.getsockname()
            peer_ip, peer_port = sock.getpeername()
            log(f"Local endpoint  : {local_ip}:{local_port}")
            log(f"Remote endpoint : {peer_ip}:{peer_port}")
        except OSError as err:
            log("Connected, but failed to inspect socket endpoints.")
            log(describe_socket_error(err))
            log(f"Raw error: {repr(err)}")

        return sock

    except OSError as err:
        log("Connection failed.")
        log(describe_socket_error(err))
        log(f"Raw error: {repr(err)}")

        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

        return None


def run_handshake_mode(sock: socket.socket) -> None:
    log("Running diagnostic handshake mode...")

    try:
        payload = HANDSHAKE_MESSAGE.encode("utf-8")
        sock.sendall(payload)
        log(f"Sent handshake message: {HANDSHAKE_MESSAGE!r}")

        try:
            reply = sock.recv(RECV_REPLY_SIZE)
        except OSError as err:
            log("Connected, but receiving the reply failed.")
            log(describe_socket_error(err))
            log(f"Raw error: {repr(err)}")
            return

        if not reply:
            log("Server closed the connection without sending a reply.")
            return

        try:
            decoded_reply = reply.decode("utf-8", errors="replace")
        except Exception:
            decoded_reply = repr(reply)

        log(f"Received reply from server: {decoded_reply!r}")

    except OSError as err:
        log("Failed during handshake mode.")
        log(describe_socket_error(err))
        log(f"Raw error: {repr(err)}")


def run_video_mode(sock: socket.socket) -> None:
    log("Running video streaming mode...")

    cap = None

    try:
        cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            log("Failed to open the drone camera.")
            return

        log("Camera opened successfully. Beginning frame transmission...")

        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        frame_counter = 0

        while True:
            ret, frame = cap.read()

            if not ret or frame is None:
                log("Failed to read frame from camera.")
                break

            success, encoded_frame = cv2.imencode(".jpg", frame, encode_params)
            if not success:
                log("Failed to encode frame.")
                continue

            frame_bytes = encoded_frame.tobytes()
            frame_size = len(frame_bytes)

            header = struct.pack("!Q", frame_size)

            try:
                sock.sendall(header)
                sock.sendall(frame_bytes)
            except OSError as err:
                log("Failed while sending frame to laptop.")
                log(describe_socket_error(err))
                log(f"Raw error: {repr(err)}")
                break

            frame_counter += 1
            log(f"Sent frame #{frame_counter} ({frame_size} bytes)")

            time.sleep(SEND_DELAY)

    except OSError as err:
        log("Socket error during video mode.")
        log(describe_socket_error(err))
        log(f"Raw error: {repr(err)}")
    except Exception as err:
        log("Unexpected error during video mode.")
        log(f"Type: {type(err).__name__}")
        log(f"Message: {err}")
        traceback.print_exc()
    finally:
        if cap is not None:
            cap.release()
            log("Camera released.")


def main() -> None:
    print_client_startup_notes()

    sock = None

    try:
        if MODE not in ("handshake", "video"):
            log("Invalid MODE value. Use 'handshake' or 'video'.")
            return

        sock = connect_to_server()
        if sock is None:
            return

        if MODE == "handshake":
            run_handshake_mode(sock)
        elif MODE == "video":
            run_video_mode(sock)

    except KeyboardInterrupt:
        log("Drone client stopped by user.")
    except Exception as err:
        log("Unexpected fatal client error.")
        log(f"Type: {type(err).__name__}")
        log(f"Message: {err}")
        traceback.print_exc()
    finally:
        if sock is not None:
            try:
                sock.close()
                log("Socket closed.")
            except Exception:
                log("Failed to close socket cleanly.")


if __name__ == "__main__":
    main()
