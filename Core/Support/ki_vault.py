import os
import json
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class KiVault:
    def __init__(self, secret_key: str | None = None):
        # Support a single explicit root of trust. Legacy node-agent secret is
        # accepted only if it is configured; there is no baked-in default.
        self.secret = secret_key or os.getenv("KIBOT_SECRET") or os.getenv("KIBOT_NODE_AGENT_SECRET")
        if not self.secret:
            raise RuntimeError("KIBOT_SECRET missing: KiVault refuses to initialize without an explicit secret")
        
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
    """Loads and decrypts environment variables from a .kiv vault file or directly from os.environ."""
    # Always try to load plain .env first if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
        
    vault = KiVault()
    
    # 1. First, scan all existing environment variables for ENC() patterns.
    # If a token cannot be decrypted, treat it as unavailable instead of
    # leaving the encoded blob in the environment where it can poison callers.
    for key, val in list(os.environ.items()):
        if isinstance(val, str) and val.startswith("ENC("):
            try:
                # Strip ENC( and )
                token = val[4:-1]
                decrypted_val = vault.decrypt(token)
                os.environ[key] = decrypted_val
            except Exception:
                os.environ.pop(key, None)

    # 2. Then load .env.kiv if it exists
    vault_path = Path(path)
    if vault_path.exists():
        print(f"[VAULT] Loading sovereign environment from {path}")
        try:
            with open(vault_path, "r") as f:
                for line in f:
                    if "=" in line:
                        key, val = line.strip().split("=", 1)
                        if val.startswith("ENC("):
                            try:
                                token = val[4:-1]
                                decrypted_val = vault.decrypt(token)
                                os.environ[key] = decrypted_val
                            except Exception:
                                os.environ.pop(key, None)
                        else:
                            os.environ[key] = val
        except Exception as e:
            print(f"[VAULT][ERROR] Could not read vault: {e}")

def get_vault():
    return KiVault()
