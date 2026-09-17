HOST = "192.168.2.168"
PORT = 1111

CA_CERT = r"C:\Users\kevin\CLionProjects\Smart_Farm\uav_control\ca\ca_cert.pem"
CLIENT_CERT = r"C:\Users\kevin\CLionProjects\Smart_Farm\uav_control\certs\drone1_cert_clean.pem"
CLIENT_KEY = r"C:\Users\kevin\CLionProjects\Smart_Farm\uav_control\keys\drone1_key_clean.pem"
HMAC_KEY = r"C:\Users\kevin\CLionProjects\Smart_Farm\uav_control\keys\hmac_key.bin"

SERVER_NAME = "192.168.2.168"
RELAX_TLS = True
REQUIRE_CLIENT_CERT = True

SOCKET_TIMEOUT = 10
READ_TIMEOUT = 10
BUFFER_SIZE = 4096
SEND_DELAY = 0.03
JPEG_QUALITY = 80
MAX_FRAME_SIZE = 10 * 1024 * 1024
CAMERA_INDEX = 0
