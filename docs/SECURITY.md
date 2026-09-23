# 🛡️ KIBOT V3 — SECURITY POLICY & GUIDELINES

## 1. Authentication & Access Hygiene

- **JANGAN PERNAH** menggunakan GitHub Personal Access Token (PAT) langsung pada command line atau server environment.
- Selalu gunakan **SSH Deploy Key (ED25519)** dengan hak akses scoped ke repository.
- Seluruh environment file (`.env`) wajib memiliki permission `600` (`chmod 600 .env`) dan dimiliki secara eksklusif oleh user `ubuntu`.

---

## 2. Indodax Exchange API Security (Kritis)

Saat membuat API Key di Indodax (`indodax.com -> Profile -> API`):
1. **View / Read Info**: `ENABLED` (Wajib untuk balance & order history).
2. **Trade**: `ENABLED` (Untuk order placement saat live mode).
3. **Withdrawal**: `DISABLED` (**MUTLAK HARUS MATI / NONAKTIF**). Sistem otomatis melakukan verifikasi bahwa penarikan dana diblokir pada level exchange API key.
4. **IP Whitelist**: Wajib memasukkan alamat IP publik server:
   - SG1: `152.69.218.198`
   - Server 2: `213.35.118.26`

---

## 3. Telegram Bot Security

- Bot token wajib diperlakukan sebagai rahasia tingkat tinggi (`TELEGRAM_BOT_TOKEN`).
- Batasi interaksi Telegram ke `TELEGRAM_CHAT_ID` terdaftar (whitelist admin). Pesan dari user ID tidak dikenal wajib diabaikan secara otomatis.
- Rotasi token Telegram dilakukan setiap 30 hari atau segera jika dicurigai ada kebocoran.
