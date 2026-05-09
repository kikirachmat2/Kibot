#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import json
import time
import hashlib
import hmac
import urllib.parse
from urllib.request import Request, urlopen

# Path setup
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from SERVER_BATAM.Support.ki_vault import get_vault

def test_indodax_credentials(api_key, api_secret):
    """Test if Indodax credentials can fetch account information."""
    url = "https://indodax.com/tapi"
    nonce = int(time.time() * 1000)
    payload = urllib.parse.urlencode({
        "method": "getInfo",
        "nonce": nonce
    })
    
    signature = hmac.new(
        api_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha512
    ).hexdigest()
    
    headers = {
        "Key": api_key,
        "Sign": signature,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    req = Request(url, data=payload.encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res.get("success") == 1:
                print("✅ Indodax Credentials Valid!")
                print(f"💰 Balance Info: {res.get('return', {}).get('balance', {})}")
                return True
            else:
                print(f"❌ Indodax Error: {res.get('error', 'Unknown error')}")
                return False
    except Exception as e:
        print(f"❌ Request Failed: {e}")
        return False

def main():
    print("--- KiBot Credential Migration ---")
    print(f"Current Working Directory: {os.getcwd()}")
    
    # Prompt for credentials (User will edit this script or we use input)
    # Since we are in an agentic environment, I'll provide placeholders.
    
    api_key = input("Enter Indodax API Key: ").strip()
    api_secret = input("Enter Indodax API Secret: ").strip()
    
    if not api_key or not api_secret:
        print("❌ Error: API Key and Secret are required.")
        return

    print("🧪 Testing credentials...")
    if not test_indodax_credentials(api_key, api_secret):
        confirm = input("Credentials failed validation. Save anyway? (y/n): ").lower()
        if confirm != 'y':
            print("Terminating.")
            return

    vault = get_vault()
    
    # We will update/create .env first, then vaultify it.
    env_file = ROOT_DIR / ".env"
    
    # Read existing .env if any
    lines = []
    if env_file.exists():
        lines = env_file.read_text().splitlines()
    
    # Update or add keys
    new_lines = []
    found_key = False
    found_secret = False
    
    for line in lines:
        if line.startswith("INDODAX_API_KEY="):
            new_lines.append(f"INDODAX_API_KEY={api_key}")
            found_key = True
        elif line.startswith("INDODAX_API_SECRET="):
            new_lines.append(f"INDODAX_API_SECRET={api_secret}")
            found_secret = True
        else:
            new_lines.append(line)
            
    if not found_key:
        new_lines.append(f"INDODAX_API_KEY={api_key}")
    if not found_secret:
        new_lines.append(f"INDODAX_API_SECRET={api_secret}")
        
    env_file.write_text("\n".join(new_lines))
    print(f"✅ Updated {env_file.name}")
    
    # Encrypt to .env.kiv
    kiv_file = ROOT_DIR / "SERVER_BATAM" / ".env.kiv"
    vault.vaultify_env(env_file, kiv_file)
    
    print(f"🚀 Credentials migrated and encrypted to {kiv_file.name}")
    print("⚠️  You can now safely delete the plaintext .env if you wish, or keep it for the executor engine.")

if __name__ == "__main__":
    main()
