# 🇯🇵 KiBot Scanner Node (Tokyo)

This node is responsible for low-latency market scanning across multiple global exchanges (Binance, Bybit, KuCoin, MEXC, Polymarket).

## 📁 Directory Structure
- **[Core/](file:///home/ubuntu/KiBot/SERVER_SCANNER/Core/)**: Multi-threaded exchange scrapers and global mesh broadcaster.
- **[Security/](file:///home/ubuntu/KiBot/SERVER_SCANNER/Security/)**: SSH keys and authentication certificates.
- **[Infrastructure/](file:///home/ubuntu/KiBot/SERVER_SCANNER/Infrastructure/)**: Systemd services for the scanner mesh.

## 🔑 SSH Access Info
- **Public IP**: `152.69.218.198`
- **Tailscale IP**: `100.105.139.21`
- **User**: `ubuntu`
- **SSH Key**: `SERVER_BATAM/Infrastructure/SSH/ssh-key-scanner.pem`

### Access via Tailscale (Recommended)
```bash
ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-scanner.pem ubuntu@100.105.139.21
```

### Access via Jump Host (Batam)
```bash
ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-scanner.pem \
    -o ProxyCommand="ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-batam-active.pem -W %h:%p ubuntu@168.110.201.228" \
    ubuntu@100.105.139.21
```
