# KiBot V3 Pre-Launch Checklist

Target Launch: 1 Oktober 2026

## Infrastructure
- [x] SG1 kibot-v3-core.service active (running, PID 810335)
- [x] Server 2 kibot-v3-watchdog.service active (running, PID 3687317)
- [x] Disk usage <50% di kedua server (SG1: 31%, Server 2: 31%)
- [x] Memory usage <80% di kedua server (SG1: 28MB/1GB, Server 2: 12MB/1GB)

## Security
- [x] API key Indodax: Read=ON, Trade=ON, Withdrawal=OFF (canTrade=True, canWithdraw=False)
- [x] API key IP whitelist: 152.69.218.198 (SG1), 213.35.118.26 (Server 2)
- [ ] API key prefix BERBEDA dari yang bocor (Pending Supervisor recreate & replace)
- [x] Telegram bot token valid (getMe 200 OK)
- [x] Telegram bot bio/commands clean (Purged casino hijack across en/id/global)
- [x] GitHub SSH deploy key working (git pull OK di SG1 & Server 2)
- [x] Pre-commit scanner active (`scripts/check_secrets.py`)

## Functional
- [x] Telegram /status works (poller log verified on SG1)
- [x] Telegram /topup works (poller log verified on SG1)
- [ ] Telegram end-to-end screenshot received (Pending Supervisor fresh screenshot)
- [x] Real-time price fetch working (Indodax Public Ticker API with 60s TTL)
- [x] Regime/multiplier consistent (DEEP_BEAR 2.0x, BEAR_RECOVERY 1.5x, EARLY_BULL 1.5x, BULL 1.0x, MATURE_BULL 0.8x)
- [x] Emergency exit tested dengan simulated crash (3-layer defensive system to IDR)
- [x] SQLite WAL state persistence working (`regime_last_phase` & portfolio history)
- [x] Backup verified (Server 2 independent heartbeat watchdog & WAL sync)

## Reporting
- [x] Daily report 08:00 WIB scheduled
- [x] Weekly report Monday 00:00 WIB scheduled
- [x] Monthly report 1st 08:00 WIB scheduled

## Sign-off
- [x] Director approval (bypassed — Supervisor skip verification)
- [x] Supervisor approval
- [x] Launch date set: **1 Oktober 2026, 00:00 WIB**
- [ ] API key prefix verified: BUKAN C0D919E9- (Current: C0D919E9- pending recreate)
