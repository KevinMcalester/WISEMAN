HOST = "0.0.0.0"
PORT = 1111

SERVER_CERT = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\public_keys\server_cert.pem"
SERVER_KEY  = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\private_keys\server_key.pem"
CA_CERT     = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\ca\ca_cert.pem"
HMAC_KEY    = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\gcs_src\security\private_keys\hmac_key.bin"

SERVER_RUNTIME_LOGS = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\logs\server_runtime.log"
TELEMETRY_LOGS = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\logs\grc_logs.json"
CONTROL_LOGS = r"C:\Users\kevin\CLionProjects\Smart_Farm\ground_control\logs\control_inputs.json"

BUFFER_SIZE = 4096
MAX_PACKET_SIZE = 65536
MAX_FRAME_SIZE = 10 * 1024 * 1024
MAX_CONNECTIONS = 4
MAX_THREADS = 20
TIME_WINDOW = 60
READ_TIMEOUT = 10
HANDSHAKE_TIMEOUT = 10

SHOW_VIDEO = True
WINDOW_NAME = "Quanser Drone Feed"
PRINT_FRAME_EVERY = 30

VALID_COMMANDS = {"HANDSHAKE", "TELEMETRY", "CONTROL"}
ALLOWED_CLIENTS = set()

SERVER_NAME = "192.168.2.168"

RELAX_TLS = True
REQUIRE_CLIENT_CERT = False
