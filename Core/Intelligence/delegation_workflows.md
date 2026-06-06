# 🧭 KiBot Delegation Workflows

Dokumen ini menjelaskan pola delegasi kerja KiBot Sovereign agar council, scanner, executor, notifier, janitor, dan AI brain bergerak sebagai satu sistem yang terkontrol.

## Prinsip
- Satu tujuan, banyak spesialis.
- Delegasi harus eksplisit, terukur, dan bisa diaudit.
- Council tetap pemegang keputusan akhir.
- Executor hanya mengeksekusi mandat yang lolos gate.
- Notifier hanya untuk sinyal penting, bukan chat log.
- Janitor menjaga sistem tetap hidup sebelum profit dikejar.

## Workflow Inti

### 1. Signal Discovery
Input:
- Scanner Indodax

Output:
- Sinyal HMAC-signed
- Metadata stage: `CONTINUATION`, `RECLAIM`, `LATE_RECLAIM`, `RANGE_BREAK_RECLAIM`, `SUPPORT_BOUNCE`, `PIVOT_RECLAIM`, `MATURE`, `IGNITION`

Aturan:
- Jangan kirim noise mentah.
- Dedupe berdasarkan UID stabil.
- Kalau depth/OBI gagal, pakai proxy struktural.

### 2. Council Deliberation
Input:
- Signals
- what-if snapshot
- evidence bundle
- daily state
- portfolio state
- antagonist view
- possibility mining
- deadline pressure

Output:
- `BUY`, `SELL`, atau `NONE`
- `ENTER`, `WAIT`, atau `EXIT`
- `learning_probe` bila perlu
- `recovery_mode` bila equity harian merah tapi masih ada waktu dan edge valid

Aturan:
- Target harian adalah `GREEN`, bukan angka persen kaku.
- Jika day green dan edge masih kuat, council boleh stay pada winner.
- Kalau evidence lemah, pilih `NONE`.
- Kalau market jelek, cari edge terbaik yang masih valid, jangan freeze.

### 3. Executor Gate
Input:
- Mandat council
- saldo live
- fee aware budget
- spread
- momentum
- confidence
- hard risk rules

Output:
- Order live atau reject

Aturan:
- Live trading hanya kalau gate eksplisit aktif.
- Harga koin harus masuk budget efektif.
- Spread, confidence, dan momentum floor tetap dijaga.
- Stage yang lebih agresif boleh melonggarkan floor, tapi tidak menghapus rem.

### 4. Verification Loop
Input:
- order result
- active trades
- PnL
- risk state
- system health

Output:
- trade log
- midnight report
- state update
- alert jika butuh bantuan operator

Aturan:
- Kalau sistem bisa recover sendiri, jangan spam Telegram.
- Telegram hanya untuk laporan malam dan insiden yang butuh manusia.

### 5. Maintenance Loop
Input:
- disk health
- Ollama health
- Redis health
- service health
- cache/log growth

Output:
- cleanup
- restart service
- model sync
- state repair

Aturan:
- Janitor jalan sebelum sistem rusak.
- Disk bloat dan stale cache harus dibersihkan otomatis.

## Delegation Matrix

| Layer | Tugas | Otoritas | Verifikasi |
|---|---|---:|---|
| Scanner | Temukan kandidat | Rendah | Council + executor |
| Antagonist | Cari kontra-thesis | Rendah | Council |
| Possibility Mining | Cari peluang alternatif | Sedang | Council |
| Council Speaker | Final mandate | Tinggi | What-if + evidence |
| Executor | Eksekusi order | Sedang | Risk gate + balance + spread |
| Verifier | Pantau hasil | Sedang | PnL + order state |
| Janitor | Jaga server | Sedang | Service health + disk |
| Notifier | Laporkan penting | Rendah | Throttle + dedupe |

## Contoh Jalur

### Pump continuation
1. Scanner menemukan continuation kuat.
2. Council membandingkan evidence dan what-if.
3. Antagonist mencoba membatalkan thesis kalau terlalu lemah.
4. Kalau edge tetap kuat, council mengeluarkan `BUY`.
5. Executor cek saldo, fee, spread, lalu eksekusi.
6. Verifier memantau posisi sampai exit edge muncul.

### Controlled recovery
1. PnL harian merah.
2. Deadline pressure naik saat menjelang midnight.
3. Council tetap mencari peluang terbaik, bukan revenge trade.
4. Jika evidence valid, sistem boleh entry kecil sebagai probe atau recovery terkontrol.
5. Kalau edge tidak cukup, council pilih `WAIT`.

### Support bounce / pivot reclaim
1. Scanner mendeteksi reclaim awal dari support.
2. Council menilai room-to-run dan struktur intraday.
3. Antagonist mengecek apakah bounce itu cuma dead cat.
4. Jika struktur masih sehat, executor boleh ambil wave kecil.
5. Kalau candle terlalu liar, sistem tetap menolak.

## Operator Rules
- Jangan reintroduce duplicate services.
- Jangan commit secrets.
- Jangan ubah live gate jadi implicit.
- Kalau state runtime berubah, update README dan inventory.
- Kalau workflow baru ditambah, catat stage dan syaratnya.
- Runtime ini Indodax-only. Jangan menghidupkan ulang route wallet eksternal, prediction market, atau chain lain.
