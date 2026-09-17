import hashlib
import hmac

key = b"shared-secret-key"
data = b'data = 12'

def generate_hmac(key, data)-> str:
    try:
        tag = hmac.new(key,data, hashlib.sha256).hexdigest()
        return tag
    except Exception as e:
        print(f"Error: {e}")

def verify_hmac(key, data, tag):
    expected_tag = hmac.new(key,data,hashlib.sha256).hexdigest()
    if hmac.compare_digest(tag, expected_tag):
        print("HMAC matches")
    else:
        print(f"HMAC doesn't match: {tag}")


if __name__ == "__main__":
    generate_hmac(key, data)
    verify_hmac(key, data, generate_hmac(key, data))

