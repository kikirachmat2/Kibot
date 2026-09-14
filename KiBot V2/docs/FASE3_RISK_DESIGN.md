# DESAIN ARSITEKTUR FASE 3: PAIR QUARANTINE & CHURN GUARD

Dokumen spesifikasi desain teknis (*Architecture Specification*) untuk komponen mitigasi risiko Fase 3 KiBot V2.

---

## 1. LATAR BELAKANG EMPIRIS (SOAK TEST SG1)
Pada pengujian soak test tanpa henti di SG1, terdeteksi pola pasar mendatar (*range-bound/chop*):
* 37 trade berturut-turut pada pasangan `BTCIDR` seluruhnya keluar melalui mekanisme waktu habis (`MAX_HOLD_TIME_EXPIRED`).
* Terjadi kebocoran biaya (*fee bleeding*) sebesar Rp 258.721 akibat akumulasi taker fee bursa (0.42% roundtrip) dan gesekan likuiditas tanpa ada pergerakan harga yang menyentuh target Take Profit (+1.8%).

Dua modul berikut dirancang untuk menghentikan pendarahan modal secara otomatis saat kondisi pasar tidak mendukung.

---

## 2. SPESIFIKASI PAIR QUARANTINE (`risk/pair_quarantine.py`)

### A. Aturan Pemicu (Trigger Conditions)
1. **Consecutive Losses**: Jika 1 pair mengalami 3 kekalahan beruntun (PnL < 0), pair dikarantina selama **24 jam (86.400 detik)**.
2. **Timeout Churn**: Jika 1 pair mengalami 3 exit berturut-turut via `MAX_HOLD_TIME_EXPIRED` tanpa pernah menyentuh TP, pair dikarantina selama **4 jam (14.400 detik)**.
3. **Permanent Blacklist**: Pasangan aset dengan rekam jejak manipulatif atau spread tidak wajar (misal `TRXIDR`).
4. **TTL-based Auto-Expiry**: Status karantina otomatis dicabut setelah batas waktu kedaluwarsa terlampaui.

### B. Catatan Desain Kritis: Perilaku Defensif Saat BTCIDR Dikarantina
> [!IMPORTANT]
> **PERILAKU DEFENSIS YANG DIINGINKAN (BUKAN BUG / BUKAN KEGAGALAN SISTEM)**:
> Dalam kondisi pasar saat ini, di mana `BTCIDR` merupakan satu-satunya pasangan aset likuid yang secara konsisten lolos ambang batas Expected Value (EV) Gate awal, **mengkarantina `BTCIDR` kemungkinan besar akan menyebabkan KiBot V2 berhenti melakukan transaksi sama sekali (*zero trades*) selama durasi karantina berlangsung**.
> 
> Sistem **TIDAK AKAN** secara ceroboh mengalihkan modal ke koin altcoin berkualitas rendah hanya demi memaksakan aktivitas trading. Periode *zero-trade* ini adalah **perilaku defensif yang memang disengaja (*by design*)** untuk melindungi ekuitas dari pengikisan biaya transaksi saat volatilitas pasar mengering. Jangan disalahartikan sebagai anomali, macet, atau bug sistem pada saat pemantauan operasional.

---

## 3. SPESIFIKASI CHURN GUARD (`risk/churn_guard.py`)

### A. Aturan Pemicu (Trigger Conditions)
1. **Rolling Profit Factor Gate**:
   * Jika dalam rolling window 10 closed trade terakhir rasio $\text{Profit Factor} < 0.80$, sistem beralih ke *Guarded Mode*:
     * Batas order harian diperketat menjadi maksimal **3 order per hari kalender**.
     * Ambang batas persetujuan EV dinaikkan dari `+0.30%` menjadi `+0.60%`.
2. **Fee Bleeding Cap**:
   * Jika total biaya komisi bursa pada hari berjalan mencapai $\ge 0.75\%$ dari ekuitas portofolio, seluruh pembukaan posisi baru dibekukan hingga pergantian hari (00:00 UTC / 07:00 WIB).

---

## 4. INTEGRASI KE CAPITAL GOVERNOR
Kedua modul akan dihubungkan langsung ke gerbang persetujuan `CapitalGovernor.can_open_position(symbol)`:
```python
# Pseudo-flow Fase 3:
# 1. Cek PairQuarantine -> Jika aktif, tolak dengan status BLOCKED_QUARANTINE
# 2. Cek ChurnGuard -> Jika guarded, terapkan kuota ketat dan EV tinggi
# 3. Cek Sector Diversification (coin_category)
# 4. Lanjut ke Stage 2 Microstructure (orderbook depth VWAP)
```

Dokumen ini disimpan sebagai cetak biru siap-eksekusi setelah jendela soak test 12–24 jam berakhir.
