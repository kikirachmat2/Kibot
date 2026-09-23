# 🚨 SECURITY INCIDENT REPORT: BOT HIJACK & RECOVERY

**Incident Date:** 2026-09-20  
**Affected Asset:** Telegram Bot `@KukiraKikiBot` (`8583424689`)  
**Classification:** Credential Compromise (Legacy V2 Bot Token Hijack)  
**Severity:** HIGH  
**Status:** CONTAINED & REMEDIATED  

---

## 1. Executive Summary

Pada 20 September 2026, selama deployment dan verifikasi integrasi Telegram untuk KiBot V3, terdeteksi bahwa profil bot `@KukiraKikiBot` telah disusupi oleh pihak ketiga tanpa izin. Penyerang menyematkan promosi situs judi casino online (`https://t.me/Xstakerobot`) pada bio bot, deskripsi bahasa Inggris (`language_code: en`), dan menu commands Telegram (`/start`).

Investigasi mengonfirmasi bahwa penyerang memanfaatkan **Bot Token lama peninggalan V2** (`8583424689:AAHRe8drD2hmuyN48RoFv9Me0oXwcXnSoSE`). Token tersebut telah di-revoke secara resmi oleh Supervisor melalui `@BotFather` pada 20 September 2026 05:25 WIB, dan seluruh konfigurasi bot telah dipulihkan secara menyeluruh.

---

## 2. Attack Vector Analysis & Forensics

1. **Credential Exposure Origin:** Bot Token Telegram lama (`8583424689:AAHRe8dr...`) tersimpan pada file `.env` di server sebelum proses migrasi ke V3.
2. **Attacker Actions Identified:**
   - **Targeted Locale Injection:** Attacker menyematkan bio berbahasa Inggris (`language_code: en`) berbunyi `✅ BEST CASINO MINI-APP https://t.me/Xstakerobot ✅`.
   - **Menu Hijack:** Perintah `/start` pada bot didaftarkan untuk mengiklankan bot casino pihak ketiga.
   - **Scope Boundary:** Penyerang **TIDAK** memiliki akses root ke server, tidak memiliki SSH key, dan tidak menyusup ke database.
3. **Webhook & Packet Inspection:**
   - Panggilan `getWebhookInfo` menghasilkan `url: ""` (tidak ada webhook aktif yang didaftarkan attacker untuk menyadap obrolan).
   - Seluruh histori `getUpdates` tidak menunjukkan pengiriman pesan massal kepada pihak ketiga dari token bot ini.

---

## 3. Impact Assessment

- **Kerahasiaan Data (Confidentiality):** LOW. Tidak ada data portofolio V3, database, atau kredensial internal yang bocor.
- **Integritas Profil Bot (Integrity):** MODERATE. Profil bot publik (bio & command description) sempat diubah menjadi teks spam casino.
- **Ketersediaan Sistem (Availability):** ZERO IMPACT. Layanan V3 tetap berjalan dan bot segera dipulihkan dalam hitungan menit setelah token dirotasi.

---

## 4. Containment Timeline (20 September 2026)

- **05:25 WIB:** Supervisor melakukan revoke token lama via `@BotFather`. Token baru (`8583424689:AAEny_jNr...`) diterbitkan.
- **05:35 WIB:** Token lama diverifikasi mati total (`401 Unauthorized`).
- **05:47 WIB:** Pembersihan mendalam: Deskripsi bot dan bio pada seluruh locale (`en`, `id`, global) ditimpa resmi dengan identitas KiBot V3.
- **05:54 WIB:** Menu commands palsu casino dibersihkan dan diganti 4 perintah resmi KiBot V3 (`/status`, `/topup`, `/withdraw`, `/report`).
- **05:58 WIB:** Pengujian live end-to-end dengan Telegram Client membuktikan bot 100% responsif dan bersih dari jejak scam.

---

## 5. Prevention for V3 & Long-Term Policy

1. **Token Rotation Lifecycle:** Token Telegram wajib dirotasi secara berkala (maksimal 30 hari) via `@BotFather`.
2. **Strict File Permissions:** Seluruh file `.env` diatur berizin `chmod 600` dan diabaikan dari git (`.gitignore`).
3. **No PAT Usage:** Seluruh akses Git di server menggunakan SSH deploy key (ED25519) dengan hak akses terbatas.
4. **Indodax API Hardening:** Seluruh kunci API bursa wajib menonaktifkan fitur withdrawal (`Withdrawal=OFF`).

---

## 6. Residual Risk Assessment

- Token lama sudah mati total (`401 Unauthorized`).
- Penyerang tidak memiliki akses ke server, database SQLite, atau private keys server.
- Insiden dinyatakan **SELESAI (RESOLVED & CLOSED)**.
