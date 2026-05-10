import os
import json
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class KiVault:
    def __init__(self, secret_key: str = None):
        self.secret = secret_key or os.getenv("KIBOT_NODE_AGENT_SECRET", "SOVEREIGN_DEFAULT_SECRET")
        self._key = self._derive_key(self.secret)
        self.fernet = Fernet(self._key)

    def _derive_key(self, secret: str) -> bytes:
        salt = b"kibot_sovereign_salt" # Standardized salt for Trinity
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
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
                        # If decryption fails, maybe it's not encrypted or key mismatch
                        print(f"[VAULT][ERROR] Failed to decrypt {key}: Decryption failed.")
                        os.environ[key] = val # Fallback to raw
    except Exception as e:
        print(f"[VAULT][ERROR] Could not read vault: {e}")

def get_vault():
    return KiVault()
