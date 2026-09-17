HOST = "192.168.2.168"
PORT = 1111

CA_CERT = "/home/nvidia/uav_control/ca/ca_cert.pem"
CLIENT_CERT = "/home/nvidia/uav_control/certs/drone1_cert.pem"
CLIENT_KEY = "/home/nvidia/uav_control/keys/drone1_key.pem"
HMAC_KEY = "/home/nvidia/uav_control/keys/hmac_key.bin"

SOCKET_TIMEOUT = 10
BUFFER_SIZE = 4096

# Important:
# If you connect by IP, do not force hostname verification against "localhost".
SERVER_NAME = "localhost"
RELAX_TLS = True
REQUIRE_CLIENT_CERT = True
