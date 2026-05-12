# 🛰️ KiBot Scanner

Scanner layer untuk membaca peluang pasar dan mengirim sinyal HMAC-signed ke executor atau council.

## Alur
- `engine.py`: orchestrator scanner, delta filter, dispatch UDP.
- `ki_indodax_smallcap_scanner.py`: deteksi pump small-cap di Indodax dengan `price_idr`.
- `ki_polymarket_full_scanner.py`: scanner peluang Polymarket.
- `ki_universal_leadlag_scanner.py`: lead-lag scanner lintas sumber global.

## Catatan Operasional
- Delta filter membandingkan harga terakhir per UID yang stabil per logical signal:
  - Indodax: `exchange:symbol`
  - Polymarket: `exchange:market_id[:outcome_index]`
  - Universal: `exchange:topic`
- Interval scanner default lebih agresif untuk flow cepat.
- Universal scanner dijalankan aman dari thread context.
