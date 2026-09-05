# 🛠️ KiBot Support

Configuration, utilities, health guards, and vault helpers.

## Ringkas
- `ki_config.py` menyimpan path dan port bersama.
- `ki_utils.py` berisi helper umum seperti signing/verification.
- `telegram_throttle.py` memusatkan throttling, dedupe, dan commit Telegram.
- `ki_vault.py` (shim; kanonikal di `Core/Security/ki_vault.py`) memuat secret dari vault ke environment saat boot dan fail-closed bila `KIBOT_SECRET` tidak tersedia.
- `sovereign_janitor.py` memantau disk dan health Ollama.
- `sovereign_disk_cleaner.py` (kanonikal di `Core/Support/`; shim di `Core/`) membersihkan nested repo, cache, dan log orphaned.
- `bin/kibotctl` adalah wrapper operasional satu pintu untuk status, doctor, tools, restart, dan sync model.
- Systemd unit canonical untuk node inti juga membaca `/home/ubuntu/KiBot/.env` dan `/home/ubuntu/KiBot/.env.kiv` bila ada, supaya `KIBOT_SECRET`, wallet, dan mode live selalu konsisten lintas boot.

## Responsibility
- **Configuration**: `ki_config.py` and `dynamic_config.py`.
- **Utilities**: Shared helper functions, system performance caching (`system_perf_cache.py`), and backward-compatible shims.
- **Health Guards**: `sovereign_janitor.py`, `sovereign_disk_cleaner.py`.
- **Operator Tools**: `populate_intelligence.py`, `deposit_cli.py`, `kibotctl tools` (Vault CLI moved to `Core/Security/ki_vault_cli.py`).
- **Search bootstrap**: `install_ai_deps.sh` now installs `ddgs` alongside the legacy DuckDuckGo package for compatibility.

## Layout Notes
- Canonical shell utilities live in [`bin/`](../bin/).
- Runtime JSON lives in top-level [`state/`](../state/), not `Core/state/`.
- Vault & crypto auth modules are housed canonically in [`Core/Security/`](../Security/) with shims retained in `Core/Support/`.
- Legacy duplicate wrappers and dead code (`ki_storage.py`) have been retired.
- Telegram messages are scarce by design; use the shared throttle helper instead of raw HTTP sends.
