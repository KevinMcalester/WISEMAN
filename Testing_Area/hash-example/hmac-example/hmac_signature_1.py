import time
import hmac
import hashlib

key =b'shared-key'
data = b'temp = 102f'

def generateHMAC(key, data)-> str | None:
    try:
        tag = hmac.new(key, data, hashlib.sha256).hexdigest()
        return tag
    except Exception as e:
        print(f"Error: {e}")
        return None

def verifyHMAC(key, data, tag):
    try:
        expectedHMAC = hmac.new(key, data, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expectedHMAC, tag):
            print("HMAC matches")
        else:
            print(f"Error: data tampered")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    tag= generateHMAC(key, data)
    verifyHMAC(key, data,tag)


