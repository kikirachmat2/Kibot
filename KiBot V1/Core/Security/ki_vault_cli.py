#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))

try:
    from Core.Support.ki_vault import KiVault
except ImportError:
    print("❌ Error: Could not import KiVault. Ensure Core/Support/ki_vault.py exists.")
    sys.exit(1)

def usage():
    print("""
KiBot Sovereign Vault CLI
=========================
Usage:
  python ki_vault_cli.py encrypt "<value>"
  python ki_vault_cli.py decrypt "<token>"
  python ki_vault_cli.py seal <env_file> <output_file>
  python ki_vault_cli.py unseal <vault_file>

Environment Variables:
  KIBOT_SECRET: The master key for encryption/decryption
  KIBOT_VAULT_SALT: Custom salt for key derivation
""")

def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1].lower()
    vault = KiVault()

    if cmd == "encrypt" and len(sys.argv) == 3:
        val = sys.argv[2]
        enc = vault.encrypt(val)
        print(f"\nLocked Secret:\n{enc}\n")
        
    elif cmd == "decrypt" and len(sys.argv) == 3:
        token = sys.argv[2]
        try:
            dec = vault.decrypt(token)
            print(f"\nUnlocked Secret:\n{dec}\n")
        except Exception as e:
            print(f"❌ Decryption failed: {e}")

    elif cmd == "seal" and len(sys.argv) >= 3:
        env_file = Path(sys.argv[2])
        out_file = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(".env.kiv")
        
        if not env_file.exists():
            print(f"❌ Source file {env_file} not found.")
            sys.exit(1)
            
        print(f"🔒 Sealing {env_file} -> {out_file}...")
        with open(env_file, "r") as f_in, open(out_file, "w") as f_out:
            for line in f_in:
                line = line.strip()
                if not line or line.startswith("#"):
                    f_out.write(line + "\n")
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    enc_val = vault.encrypt(val)
                    f_out.write(f"{key}={enc_val}\n")
        print("✅ Vault sealed successfully.")

    elif cmd == "unseal" and len(sys.argv) == 3:
        vault_file = Path(sys.argv[2])
        if not vault_file.exists():
            print(f"❌ Vault file {vault_file} not found.")
            sys.exit(1)
            
        print(f"🔓 Unsealing {vault_file}...")
        with open(vault_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    try:
                        dec = vault.decrypt(val)
                        print(f"{key}={dec}")
                    except:
                        print(f"{key}=[FAILED TO DECRYPT]")

    else:
        usage()

if __name__ == "__main__":
    main()
