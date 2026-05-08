# 🎖️ KiBot High Command (Batam)

The master node of the Trinity Mesh. Responsible for signal validation, AI veto, portfolio management, and Telegram orchestration.

## 📁 Directory Structure
- **[Core/](file:///home/ubuntu/KiBot/SERVER_BATAM/Core/)**: Decision engine and sovereign arbitrator.
- **[Intelligence/](file:///home/ubuntu/KiBot/SERVER_BATAM/Intelligence/)**: AI Orchestration, Models, and RAG.
- **[Infrastructure/](file:///home/ubuntu/KiBot/SERVER_BATAM/Infrastructure/)**: System-wide automation and SSH control.
- **[Data/](file:///home/ubuntu/KiBot/SERVER_BATAM/Data/)**: Live state, logs, and testing sandbox.

## 🔑 SSH Access Info
- **Public IP**: `168.110.201.228`
- **Tailscale IP**: `100.122.1.109` (Primary Mesh IP)
- **User**: `ubuntu`
- **SSH Key**: `SERVER_BATAM/Infrastructure/SSH/ssh-key-batam-active.pem`

### Direct SSH
```bash
ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-batam-active.pem ubuntu@168.110.201.228
```
