# 🛠️ KiBot Support

Configuration, utilities, health guards, and vault helpers.

## Ringkas
- `ki_config.py` menyimpan path dan port bersama.
- `ki_utils.py` berisi helper umum seperti signing/verification.
- `ki_vault.py` memuat secret dari vault ke environment saat boot.
- `sovereign_janitor.py` memantau disk dan health Ollama.
- `sovereign_disk_cleaner.py` membersihkan nested repo, cache, dan log orphaned.
- `bin/kibotctl` adalah wrapper operasional satu pintu untuk status, doctor, restart, dan sync model.

## Responsibility
- **Configuration**: `ki_config.py` and `dynamic_config.py`.
- **Utilities**: Shared helper functions, storage helpers, and vault management.
- **Health Guards**: `sovereign_janitor.py`, `sovereign_disk_cleaner.py`.
- **Operator Tools**: `generate_wallet.py`, `ki_vault_cli.py`, `populate_intelligence.py`.

## Layout Notes
- Canonical shell utilities live in [`bin/`](../bin/).
- Runtime JSON lives in top-level [`state/`](../state/), not `Core/state/`.
- Legacy duplicate wrappers under `Core/Support/` have been retired where possible.
