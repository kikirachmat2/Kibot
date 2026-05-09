
import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path("/Users/kiki/Documents/Web Develop/KiBot/SERVER_BATAM")
sys.path.append(str(project_root))

from Support.ki_vault import SovereignVault

# Set the secret to match the server's expected secret
os.environ["KIBOT_SECRET"] = "kibot_sovereign_trinity_mesh_2024_batam"

vault = SovereignVault()
env_file = project_root / ".env"
kiv_file = project_root / ".env.kiv"

print(f"Encrypting {env_file} using KIBOT_SECRET...")
vault.vaultify_env(env_file, kiv_file)
print("Done.")
