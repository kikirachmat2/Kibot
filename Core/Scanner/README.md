# 🛰️ KiBot Scanner

Scanner layer untuk membaca peluang pasar dan mengirim sinyal HMAC-signed ke Council. Direct-to-executor sekarang opt-in saja agar raw leaderboard pump tidak bisa bypass deliberasi.

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
- Mode `pullback_reclaim` juga ada: jika coin sempat retrace dari high tapi mulai reclaim lagi dengan volume dan persistence yang kuat, scanner tetap menganggapnya kandidat second-leg, bukan coin mati.
- Mode `late_reclaim` juga ada untuk wave yang lebih jauh dari high, tapi hanya kalau recovery score dan volume persistence masih cukup sehat. Ini menjaga sistem tetap agresif tanpa jadi liar.
- Mode `range_break_reclaim` juga ada untuk setup yang keluar dari range intraday lalu reclaim lagi dengan volume lanjutan. Ini dibuat untuk menangkap second-wave yang lebih kuat, tapi tetap tidak dipakai kalau struktur sudah rusak.
- Mode `support_bounce_reclaim` juga ada untuk coin yang memantul dari support intraday lalu reclaim lagi dengan room to run yang masih sehat. Ini membuat scanner lebih peka ke riding-the-wave tanpa jadi terlalu liar.
- Mode `pivot_reclaim` juga ada untuk reclaim yang sangat awal, saat coin baru memantul dari pivot intraday dan masih punya room untuk lanjut. Ini dipakai untuk menangkap wave yang belum sempat kelihatan besar, tapi tetap dibatasi agar tidak jadi entry ngawur.
- Kalau depth/OBI Indodax sedang tidak bisa diakses dari server, scanner memakai proxy struktural dari run-up, range position, persistence, dan volume sehingga pump detection tetap hidup.
- Default dispatch ke executor dimatikan. Gunakan `KIBOT_SCANNER_DIRECT_INDODAX=1` atau `KIBOT_SCANNER_DIRECT_POLYMARKET=1` hanya untuk debug sadar risiko.
- Anti tick-trap aktif: coin dengan `price_increment / price` terlalu besar, level harga 24h terlalu sedikit, spread terlalu lebar, OBI condong jual, atau OHLC datar akan ditolak sebelum confidence score.
- Endpoint depth Indodax memakai compact pair resmi seperti `/api/depth/btcidr`; ini penting karena `/api/depth/btc_idr` menghasilkan `invalid_pair`.
- Interval scanner default lebih agresif untuk flow cepat.
- Universal scanner dijalankan aman dari thread context.
- Universal lead-lag signals are context only unless Council can match them to a supported executor route. Deterministic fallback is not allowed to turn generic exchange/entity signals into Indodax buy orders.
