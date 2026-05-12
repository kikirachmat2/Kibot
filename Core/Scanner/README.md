# 🛰️ KiBot Scanner

Scanner layer untuk membaca peluang pasar dan mengirim sinyal HMAC-signed ke executor atau council.

## Alur
- `engine.py`: orchestrator scanner, delta filter, dispatch UDP.
- `ki_indodax_smallcap_scanner.py`: deteksi pump small-cap di Indodax dengan `price_idr`, plus 24h run-up, near-high continuation, dan volume persistence.
- `ki_polymarket_full_scanner.py`: scanner peluang Polymarket.
- `ki_universal_leadlag_scanner.py`: lead-lag scanner lintas sumber global.

## Catatan Operasional
- Delta filter membandingkan harga terakhir per UID yang stabil per logical signal:
  - Indodax: `exchange:symbol`
  - Polymarket: `exchange:market_id[:outcome_index]`
  - Universal: `exchange:topic`
- Indodax pump scanner sekarang tidak hanya baca 5m momentum, tetapi juga 24h proxy run-up, jarak ke high harian, dan volume persistence supaya pump continuation tetap bisa ditembus.
- Kalau depth/OBI Indodax sedang tidak bisa diakses dari server, scanner memakai proxy struktural dari run-up, range position, persistence, dan volume sehingga pump detection tetap hidup.
- Interval scanner default lebih agresif untuk flow cepat.
- Universal scanner dijalankan aman dari thread context.
