import secrets
from eth_account import Account

def generate_sovereign_wallet():
    """Generates a new secure Polygon/Ethereum wallet."""
    # Enable unofficial features to avoid warnings
    Account.enable_unaudited_hdwallet_features()
    
    # Generate a random 32-byte entropy for the private key
    priv = secrets.token_hex(32)
    private_key = "0x" + priv
    
    # Create account object
    acct = Account.from_key(private_key)
    
    print("\n\033[92m✨ NEW SOVEREIGN WALLET GENERATED ✨\033[0m")
    print("------------------------------------------")
    print(f"📍 Wallet Address: \033[94m{acct.address}\033[0m")
    print(f"🔑 Private Key:    \033[91m{private_key}\033[0m")
    print("------------------------------------------")
    print("\n\033[93m⚠️  IMPORTANT SECURITY WARNING:\033[0m")
    print("1. Salin 'Private Key' ini ke file .env lu.")
    print("2. JANGAN PERNAH kasih tau private key ini ke siapapun.")
    print("3. Pindahkan saldo secukupnya (USDC & MATIC) ke 'Wallet Address' di atas.")
    print("4. Hapus script ini setelah lu selesai nyalin kuncinya.")

if __name__ == "__main__":
    generate_wallet = input("Generate dompet baru sekarang? (y/n): ")
    if generate_wallet.lower() == 'y':
        generate_sovereign_wallet()
