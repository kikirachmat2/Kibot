import os
from Core.Support.ki_vault import KiVault
from dotenv import load_dotenv

load_dotenv()
vault = KiVault()

keys_to_check = [
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "COHERE_API_KEY",
    "FINNHUB_API_KEY"
]

for key in keys_to_check:
    val = os.getenv(key)
    if val and val.startswith("ENC("):
        try:
            # Strip ENC( and )
            raw_token = val[4:-1]
            decrypted = vault.decrypt(raw_token)
            print(f"{key}: {decrypted}")
        except Exception as e:
            print(f"{key}: FAILED TO DECRYPT ({e})")
    else:
        print(f"{key}: {val}")
