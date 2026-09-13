# KiBot Sovereign — System Commander Specification

> Purpose: define the non-trading brain that keeps KiBot healthy and safe.

---

## Mission

System Commander owns system health. It does not decide trades directly. It
decides whether the system is healthy enough for trading decisions to be trusted.

Doctrine:

```text
If KiBot is blind, KiBot must not pretend to be brave.
```

---

## Inputs

- systemd service status,
- disk/RAM/CPU,
- port status,
- Redis ping,
- Ollama API and model list,
- Indodax read-only health,
- Telegram notifier health,
- AI provider state,
- web/source health,
- state file freshness,
- GitHub/server drift,
- backup status,
- config validation result,
- dashboard health.

---

## Output

`state/system_commander.json`

```json
{
  "system_state": "HEALTHY",
  "trading_allowed": true,
  "degraded_reasons": [],
  "blind_reasons": [],
  "unsafe_reasons": [],
  "services": {},
  "resources": {},
  "models": {},
  "providers": {},
  "sources": {},
  "state_files": {},
  "drift": "SYNCED",
  "backup": {},
  "actions_taken": [],
  "operator_required": false,
  "updated_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

---

## State Classification

`HEALTHY`

- all critical runtime checks pass.

`DEGRADED`

- non-critical subsystem impaired, trading may continue carefully.

`RECOVERING`

- recovery action in progress.

`BLIND`

- data freshness or balance visibility is insufficient.

`UNSAFE`

- live trading should pause because state/account/system integrity is uncertain.

---

## Recovery Actions

Allowed:

- restart known service,
- vacuum safe logs,
- clear safe cache,
- refresh telemetry,
- reset expired provider cooldown,
- rebuild non-critical cache,
- write incident record.

Forbidden:

- delete secrets,
- delete active trade state without backup,
- alter wallet/private keys,
- force git reset,
- silently enable/disable live trading,
- place or close trades directly.

---

## Dashboard Requirements

Dashboard must show:

- current system state,
- reasons,
- last actions,
- what is recoverable,
- what needs operator,
- data freshness,
- inventory utilization score.
