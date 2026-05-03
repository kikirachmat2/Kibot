#!/usr/bin/env python3
"""
KiBot Sovereign Vault
=====================
Handles encryption and decryption of sensitive secrets (API Keys, tokens).
Uses Fernet (AES-256) with a key derived from hardware unique identifiers.
"""

import os
import base64
import hashlib
import uuid
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class SovereignVault:
    def __init__(self, salt_file: Optional[Path] = None):
        self.root = Path(__file__).resolve().parent.parent
        self.salt_file = salt_file or (self.root / "state" / ".vault_salt")
        self._key: Optional[bytes] = None
        self._fernet: Optional[Fernet] = None

    def _get_hardware_id(self) -> str:
        """Get a unique hardware ID (MAC address + system node)."""
        node = uuid.getnode()
        return f"KIBOT-HW-{node}"

    def _get_or_create_salt(self) -> bytes:
        if self.salt_file.exists():
            return self.salt_file.read_bytes()
        
        # Create state dir if missing
        self.salt_file.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        self.salt_file.write_bytes(salt)
        # Set restricted permissions
        self.salt_file.chmod(0o600)
        return salt

    def _initialize(self):
        if self._fernet:
            return

        hw_id = self._get_hardware_id().encode()
        salt = self._get_or_create_salt()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(hw_id))
        self._key = key
        self._fernet = Fernet(key)

    def encrypt(self, data: str) -> str:
        self._initialize()
        return self._fernet.encrypt(data.encode()).decode()

    def decrypt(self, token: str) -> str:
        self._initialize()
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except Exception as e:
            raise ValueError(f"Decryption failed. Vault key may be invalid for this hardware. Error: {e}")

    def vaultify_env(self, env_path: Path, out_path: Path):
        """Encrypt a standard .env file into a .env.kiv file."""
        if not env_path.exists():
            print(f"[VAULT] Source .env not found: {env_path}")
            return

        lines = env_path.read_text(encoding="utf-8").splitlines()
        vault_lines = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                vault_lines.append(line)
                continue
            
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'").strip('"')
            
            # Encrypt the value
            enc_v = self.encrypt(v)
            vault_lines.append(f"{k}=ENC({enc_v})")
        
        out_path.write_text("\n".join(vault_lines), encoding="utf-8")
        out_path.chmod(0o600)
        print(f"[VAULT] Successfully encrypted {env_path.name} -> {out_path.name}")

# Singleton instance
_vault = SovereignVault()

def get_vault():
    return _vault

if __name__ == "__main__":
    # CLI for quick encryption
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "encrypt" and len(sys.argv) > 2:
            print(_vault.encrypt(sys.argv[2]))
        elif cmd == "decrypt" and len(sys.argv) > 2:
            print(_vault.decrypt(sys.argv[2]))
        elif cmd == "setup":
            root = Path(__file__).resolve().parent.parent
            _vault.vaultify_env(root / ".env", root / ".env.kiv")
