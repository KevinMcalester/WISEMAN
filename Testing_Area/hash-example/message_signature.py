import hashlib
import ground_control.gcs_src.older_src.config as config
def generate_hash(data:str) -> str | None:
    if not data:
        return None
    data = data.encode('utf-8')
    data = hashlib.sha256(data).hexdigest()
    return data



data = config.HMAC_KEY
generated_hash = generate_hash(data)
print(f"sha-256- {generated_hash}")
print(f"text:'{data}'")
