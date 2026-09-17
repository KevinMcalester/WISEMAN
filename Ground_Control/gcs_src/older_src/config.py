# Server
SERVER_CERT = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\public_keys\server_cert.pem"
SERVER_KEY  = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\private_keys\server_key.pem"
CA_CERT     = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\ca\ca_cert.pem"
HMAC_KEY    = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\private_keys\hmac_key.bin"
SERVER_RUNTIME_LOGS = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\logs\server_runtime.log"
TELEMETRY_LOGS = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\logs\grc_logs.json"

PORT = 1111

# Use 0.0.0.0 on the laptop/server so the drone can reach it
HOST = "0.0.0.0"

BUFFER_SIZE = 4096

# Keep command packets small but realistic
MAX_PACKET_SIZE = 65536

# Separate limit for video frames
MAX_FRAME_SIZE = 10 * 1024 * 1024

TIME_WINDOW = 10
MAX_CONNECTIONS = 4
MAX_THREADS = 20
READ_TIMEOUT = 10
HANDSHAKE_TIMEOUT = 10
SOCKET_TIMEOUT = 10

ALLOWED_CLIENTS = [
    "drone1",
    "ground_station",
    "admin_console"
]

VALID_COMMANDS = [
    "HANDSHAKE",
    "TELEMETRY",
    "HEARTBEAT",
    "STATUS",
    "TAKEOFF",
    "LAND",
    "STOP",
    "RETURN_HOME",
    "WAYPOINT"
]

SHOW_VIDEO = True
WINDOW_NAME = "Quanser Drone Feed"
PRINT_FRAME_EVERY = 30
JPEG_QUALITY = 80
SEND_DELAY = 0.03
