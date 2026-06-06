# 🛠️ KiBot Support

Configuration, utilities, health guards, and vault helpers.

## Ringkas
- `ki_config.py` menyimpan path dan port bersama.
- `ki_utils.py` berisi helper umum seperti signing/verification.
- `telegram_throttle.py` memusatkan throttling, dedupe, dan commit Telegram.
- `ki_vault.py` memuat secret dari vault ke environment saat boot dan fail-closed bila `KIBOT_SECRET` tidak tersedia.
- `sovereign_janitor.py` memantau disk dan health Ollama.
- `sovereign_disk_cleaner.py` membersihkan nested repo, cache, dan log orphaned.
- `bin/kibotctl` adalah wrapper operasional satu pintu untuk status, doctor, tools, restart, dan sync model.
- Systemd unit canonical untuk node inti juga membaca `/home/ubuntu/KiBot/.env` dan `/home/ubuntu/KiBot/.env.kiv` bila ada, supaya `KIBOT_SECRET`, wallet, dan mode live selalu konsisten lintas boot.

## Responsibility
- **Configuration**: `ki_config.py` and `dynamic_config.py`.
- **Utilities**: Shared helper functions, storage helpers, and vault management.
- **Health Guards**: `sovereign_janitor.py`, `sovereign_disk_cleaner.py`.
- **Operator Tools**: `ki_vault_cli.py`, `populate_intelligence.py`, `kibotctl tools`.
- **Search bootstrap**: `install_ai_deps.sh` now installs `ddgs` alongside the legacy DuckDuckGo package for compatibility.

## Layout Notes
- Canonical shell utilities live in [`bin/`](../bin/).
- Runtime JSON lives in top-level [`state/`](../state/), not `Core/state/`.
- Legacy duplicate wrappers under `Core/Support/` have been retired where possible.
- Telegram messages are scarce by design; use the shared throttle helper instead of raw HTTP sends.
