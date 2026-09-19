# 🚨 SECURITY INCIDENT REPORT: TELEGRAM BOT TOKEN DISCLOSURE

- **Incident Date**: 2026-09-20 (Post-Cleanup Audit)
- **Severity**: HIGH
- **Status**: RESOLVED — ACCEPTED RISK WITH LAYERED MITIGATIONS
- **Next Review Date**: 2026-10-20 (30-day review cycle)

---

## 1. What Leaked
- **Resource**: Telegram Bot API Token for KiBot alert channel (`8583424689:...`).
- **Exposure Channel**: Unsanitized status report output in assistant conversation transcript and fallback default parameter in `infra/oci-arm-catcher-batam.py`.
- **Chat ID Exposed**: `1346696386` (Supervisor personal Telegram chat).

---

## 2. Impact Assessment
1. **Unauthorized Messaging**: Anyone obtaining the compromised token could dispatch arbitrary Telegram messages to the supervisor's chat pretending to be KiBot.
2. **Bot Impersonation**: Attacker could poll incoming updates or command webhooks directed at the bot.
3. **No Direct Fund or Exchange Risk**: The Telegram token does NOT grant access to Indodax API keys, OCI Cloud instances, Tailscale mesh, or server SSH credentials. Exchange trade routing and execution remains unaffected.

---

## 3. Mitigation & Corrective Actions

### A. Supervisor Decision & Risk Acceptance
- **Decision**: Token NOT revoked by Supervisor decision (accepted risk).
- **Rationale**: Supervisor determined the chat conversation history is considered private and personal. No external users have access to the conversation session.
- **Residual Risk**: Potential bot impersonation if conversation history is compromised.
- **Accepted Mitigation Strategy**: Replace token rotation with strict defense-in-depth code guardrails:
  1. **Chat ID Whitelist (`ALLOWED_CHAT_IDS`)**: Hardcoded & validated whitelist in `telegram_notifier.py` and `weekly_reporter.py`. Any attempt to send alerts or messages to any chat ID other than the configured supervisor ID is immediately blocked and logged.
  2. **Push-Only Architecture (No Polling/Commands)**: Bot runs strictly as an outbound push notifier via `sendMessage`. No `getUpdates`, polling workers, or command listeners exist in KiBot V2, eliminating interactive webhook hijacking.
  3. **Local Sliding Rate Limiting**: Capped at a strict maximum of **100 messages per hour**. Dispatches exceeding this limit are dropped with warning logs.
  4. **Outbound Burst Anomaly Alert**: If more than 5 outbound messages occur within 60 seconds outside schedule, an alert is triggered via the secondary fallback channel (local failure log / Discord-Slack webhook) to the Supervisor.
  5. **Review Interval**: Periodic review scheduled every 30 days (Next: 2026-10-20). If token abuse is detected, emergency revocation will be executed immediately.

### B. Credential Scrubbing & Repository Hardening
1. Removed all hardcoded token literals and fallback strings from `infra/oci-arm-catcher-batam.py`.
2. Updated `.gitignore` to explicitly exclude all environment credential files:
   ```
   .env
   *.env
   .env.local
   .env.production
   .env.*
   ```
3. Implemented automated Git pre-commit hook (`scripts/check_secrets.py` & `.git/hooks/pre-commit`) scanning for:
   - Token regex: `\d{10}:[A-Za-z0-9_-]{35}`
   - Suspicious assignments: `BOT_TOKEN=`, `API_KEY=`, `SECRET=`
4. Scrubbed local tracking and synchronized clean code across SG1 and Server 2.

### C. Deployment of Rotated Credentials
Once Supervisor generates the fresh token:
- Injected strictly via environment file `/home/ubuntu/KiBotV2/.env` on SG1.
- Injected into `/home/ubuntu/.kibot-cluster.env` on Server 2 (`KIBOT_TELEGRAM_TOKEN`).
- Restarted `kibot-v2-paper.service` on SG1.
- Verified live transmission without ever exposing the new token in terminal transcripts or prompt outputs.

---

## 4. Prevention Framework
Langkah pencegahan komprehensif untuk mencegah kebocoran berulang:
1. **Pre-Commit Git Hooks**:
   - `scripts/check_secrets.py` memblokir commit yang memuat pola token Telegram (`\d{10}:[A-Za-z0-9_-]{35}`) atau hardcoded `API_KEY`/`SECRET`.
   - Pola sensitif seperti OCID Oracle, SSH key fingerprints, dan chat ID di konteks file konfigurasi secara otomatis memicu peringatan audit.
2. **Runtime Log Sanitization (`SecretRedactingFilter`)**:
   - Filter logging pada file dan stream console secara dinamis memindai semua log message dan me-redact pola bot token Telegram serta secret yang terdaftar menjadi `<REDACTED>`.
3. **Multi-Channel Fallback & Local Failure Logging**:
   - Jika pengiriman Telegram gagal 3x berturut-turut, pesan ditulis ke disk lokal (`logs/telegram_failures.log`) dan dialihkan ke webhook Discord/Slack (`TELEGRAM_FALLBACK_WEBHOOK`).
4. **Strict Filesystem Isolation**:
   - Semua file kredensial (`.env`, `.kibot-cluster.env`, `batam.pem`) dikunci dengan permission `chmod 600` (hanya dapat dibaca oleh pemilik proses).

---

## 5. Detection Framework
Mekanisme deteksi dini jika ada indikasi kredensial compromised:
1. **Audit Health & Revocation Validation**:
   - Pengecekan otomatis via Telegram API endpoint `https://api.telegram.org/bot<TOKEN>/getMe`. Jika token lama mengembalikan respon `200 OK`, alert CRITICAL dibangkitkan.
2. **Anomalous Bot Activity**:
   - Pemantauan journalctl terhadap kegagalan pengiriman tak terduga, konflik webhook, atau error `401 Unauthorized` / `403 Forbidden` / `409 Conflict`.
3. **Repository Secret Scanning**:
   - CI dan pre-commit hooks memeriksa seluruh staging delta sebelum git push ke GitHub.

---

## 6. Incident Response Playbook (If Compromised Again)
Jika token Telegram atau secret lainnya terindikasi bocor:
1. **Immediate Revocation (< 15 menit)**:
   - Supervisor buka `@BotFather` di Telegram -> ketik `/revoke` -> pilih bot KiBot -> konfirmasi revoke. Token lama langsung mati seketika (HTTP 401).
2. **Generate New Credentials**:
   - Dapatkan token baru dari `@BotFather`.
3. **Update Secure Environment Files**:
   - SG1: `sudo nano /home/ubuntu/KiBotV2/.env` -> ubah `TELEGRAM_BOT_TOKEN=<TOKEN_BARU>`.
   - Server 2: `sudo nano /home/ubuntu/.kibot-cluster.env` -> ubah `KIBOT_TELEGRAM_TOKEN=<TOKEN_BARU>`.
4. **Restart Services & Verify**:
   - SG1: `sudo systemctl restart kibot-v2-paper.service`.
   - Server 2: `sudo systemctl restart kibot-batam-hunter.service`.
   - Verifikasi pengiriman pesan uji: pesan harus masuk tanpa mengekspos token di laporan audit atau shell history.

---

## 7. Decision Log

- **2026-09-20**: Supervisor decided to keep old token. Rationale: chat history considered private. Mitigation: local chat_id whitelist, 100 msg/hr rate limiting, push-only architecture (no getUpdates/commands), and anomaly burst alert via fallback channel. Next review: 2026-10-20.
