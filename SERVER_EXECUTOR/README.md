# 🇸🇬 KiBot Executor Node (Singapore)

This node is responsible for high-frequency order execution and managing the interface with the Indodax/Binance exchange APIs.

## 📁 Directory Structure
- **[Core/](file:///home/ubuntu/KiBot/SERVER_EXECUTOR/Core/)**: The high-performance Kotlin-based Execution Engine (`mac-engine`).
- **[Infrastructure/](file:///home/ubuntu/KiBot/SERVER_EXECUTOR/Infrastructure/)**: Systemd units and automation scripts.
- **[Legacy/](file:///home/ubuntu/KiBot/SERVER_EXECUTOR/Legacy/)**: Older signal processing scripts.
- **[Data/](file:///home/ubuntu/KiBot/SERVER_EXECUTOR/Data/)**: Local trade logs and execution state.

## 🔑 SSH Access Info
- **Public IP**: `213.35.118.26`
- **Tailscale IP**: `100.122.1.109`
- **User**: `ubuntu`
- **SSH Key**: `SERVER_BATAM/Infrastructure/SSH/ssh-key-executor.pem`

### Access via Tailscale (Recommended)
```bash
ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-executor.pem ubuntu@100.122.1.109
```

### Access via Jump Host (Batam)
```bash
ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-executor.pem \
    -o ProxyCommand="ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-batam-active.pem -W %h:%p ubuntu@168.110.201.228" \
    ubuntu@100.122.1.109
```
