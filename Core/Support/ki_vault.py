import os
import json
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class KiVault:
    def __init__(self, secret_key: str = None):
        # Support multiple legacy and current secret keys
        self.secret = secret_key or \
                      os.getenv("KIBOT_SECRET") or \
                      os.getenv("KIBOT_NODE_AGENT_SECRET") or \
                      "SOVEREIGN_DEFAULT_SECRET"
        
        self.salt = os.getenv("KIBOT_VAULT_SALT", "kibot_sovereign_salt").encode()
        self._key = self._derive_key(self.secret)
        self.fernet = Fernet(self._key)

    def _derive_key(self, secret: str) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(secret.encode()))

    def encrypt(self, data: str) -> str:
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self.fernet.decrypt(token.encode()).decode()

def load_sovereign_env(path: str = ".env.kiv"):
    """Loads and decrypts environment variables from a .kiv vault file."""
    vault_path = Path(path)
    if not vault_path.exists():
        print(f"[VAULT][WARN] Vault file {path} not found.")
        return

    vault = KiVault()
    print(f"[VAULT] Loading sovereign environment from {path}")
    try:
        with open(vault_path, "r") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    try:
                        decrypted_val = vault.decrypt(val)
                        os.environ[key] = decrypted_val
                    except Exception:
                        # If decryption fails, check if it was supposed to be encrypted
                        if val.startswith("ENC("):
                            print(f"[VAULT][ERROR] Failed to decrypt {key}: Key mismatch or missing secret.")
                            # DO NOT set the environment variable to the raw ENC string, 
                            # as it will cause crashes later in config (e.g. int() conversion)
                        else:
                            # Not an ENC string, maybe just a normal value in the vault
                            os.environ[key] = val
    except Exception as e:
        print(f"[VAULT][ERROR] Could not read vault: {e}")

def get_vault():
    return KiVault()
