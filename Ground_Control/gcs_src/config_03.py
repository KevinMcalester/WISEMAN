HOST = "0.0.0.0"
PORT = 1111

SERVER_CERT = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\public_keys\server_cert.pem"
SERVER_KEY = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\private_keys\server_key.pem"
HMAC_KEY = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\private_keys\hmac_key.bin"

SERVER_RUNTIME_LOGS = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\logs\server_runtime.log"
TELEMETRY_LOGS = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\logs\grc_logs.json"
CONTROL_LOGS = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\logs\control_inputs.json"

BUFFER_SIZE = 4096
MAX_PACKET_SIZE = 65536
MAX_FRAME_SIZE = 10 * 1024 * 1024
MAX_CONNECTIONS = 1000
MAX_THREADS = 20
TIME_WINDOW = 60
READ_TIMEOUT = 10
HANDSHAKE_TIMEOUT = 10

WINDOW_NAME = "Quanser Drone Feed"
PRINT_FRAME_EVERY = 30
SHOW_VIDEO = True

VALID_COMMANDS = {"HANDSHAKE", "TELEMETRY", "CONTROL"}

ALLOWED_CLIENTS = set()
PILOT_CLIENT_IDS = {"pilot_laptop", "drone1"}
DRONE_CLIENT_IDS = set()

SERVER_NAME = "192.168.2.168"

CA_CERT = r"C:\Users\kevin\CLionProjects\Smart_Farm\uav_control\ca\ca_cert.pem"
CLIENT_CERT = r"C:\Users\kevin\CLionProjects\Smart_Farm\uav_control\certs\drone1_cert.pem"
CLIENT_KEY = r"C:\Users\kevin\CLionProjects\Smart_Farm\uav_control\keys\drone1_key.pem"

RELAX_TLS = True
REQUIRE_CLIENT_CERT = True

