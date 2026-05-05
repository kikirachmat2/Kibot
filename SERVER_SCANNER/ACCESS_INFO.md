# 👁️ Scanner Server Access Info

**Public IP**: `152.69.218.198`
**Tailscale IP**: `100.105.139.21`
**User**: `ubuntu`
**SSH Key**: `SERVER_BATAM/Infrastructure/SSH/ssh-key-scanner.pem` (Local)

## How to Access
If direct access to Public IP fails (due to Tailscale lockdown), use Batam as a jump host:

```bash
ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-scanner.pem \
    -o ProxyCommand="ssh -i SERVER_BATAM/Infrastructure/SSH/ssh-key-batam-active.pem -W %h:%p ubuntu@168.110.201.228" \
    ubuntu@100.105.139.21
```
