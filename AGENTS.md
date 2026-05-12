# KiBot Sovereign Agent Instructions

These instructions apply to Codex, Aider, Copilot, and GitHub-based automation that works in this repository.

## Operating Principles
- Treat `systemd` as the source of truth for runtime services on Batam.
- Use [`bin/kibotctl`](./bin/kibotctl) as the operator entrypoint for status, doctor, restart, model sync, and toolchain checks.
- Do not reintroduce duplicate services or legacy helper daemons that already have canonical replacements.
- Live trading must stay behind an explicit gate. `KIBOT_LIVE_TRADING_ENABLED` or `KIBOT_TRADING_MODE=live` must be set before any real-money order can be opened.
- Telegram is a scarce channel. Prefer the shared throttled helper and avoid duplicate or noisy notifications.
- Update README and inventory docs whenever server state, model sets, or operator tooling changes.

## Tooling
- `gh` should be used for GitHub status, repo inspection, and publishing changes when available.
- `copilot` should be treated as a server-side assistant, not as a runtime dependency.
- `aider` is available on the server via `pipx`; use it for targeted code edits when it adds value.
- If `~/.local/bin` is missing from PATH on the server, prefer the wrapper or explicit path rather than editing shell profiles inside the repo.

## Safety
- Never commit secrets, `.env`, or decrypted vault material.
- Keep the council, executors, and notifier aligned with a single runtime contract.
- If a change affects live trading, Telegram behavior, or server health, document it in the relevant README and inventory file.
