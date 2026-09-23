# KiBot V3 Paper Trade Protocol — Oktober 2026

## Timeline
- Start: 1 Oktober 2026, 00:00 WIB
- End: 31 Oktober 2026, 23:59 WIB
- Evaluasi: 1 November 2026, 08:00 WIB

## Yang Dipantau
### Harian (08:00 WIB)
- Sistem health
- Portfolio NAV
- Alokasi aset
- Event 24 jam (topup/withdraw)
- Regime status

### Mingguan (Senin 00:00 WIB)
- PnL minggu vs BTC benchmark
- Top performer / worst performer
- Rebalance activity

### Bulanan (1 Nov 08:00 WIB)
- Total modal disetor
- Cost basis per aset
- Yield dari Earn
- Manual vs auto events log
- Rekomendasi ke Supervisor

## Success Criteria (Lulus Paper Trade)
- 31 daily reports terkirim tepat waktu
- 4 weekly reports terkirim
- 1 monthly report (1 Nov)
- 0 critical crash
- 0 data integrity issue
- Emergency exit tested successfully
- Regime classification consistent (no whipsaw)

## Failure Criteria (Undur Live)
- >3 critical crashes
- Data integrity issue (equity double-count, state corrupt)
- Emergency exit fail
- Regime inconsistency >5x

## Supervisor Test Events
Minimal test selama Oktober:
- 3× /topup (variabel: 500k, 800k, 1jt)
- 1× Uji manual sell/withdraw via aplikasi Indodax (verifikasi deteksi pasif bot)
- 1× /report manual
- 1× /status daily check
