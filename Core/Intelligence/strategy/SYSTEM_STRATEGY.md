# KiBot Sovereign — System Strategy

> Scope: everything outside direct trading strategy.
> Trading logic lives in `Core/Intelligence/strategy/TRADING_STRATEGY.md`.
> This document defines how KiBot keeps itself alive, observable, maintainable,
> secure, synchronized, and useful as an autonomous system.

---

## 1. Core Doctrine

KiBot is not only a trading bot. KiBot is an autonomous operating system for a
trading agency.

System doctrine:

```text
Trading intelligence is useless if the system is blind, unhealthy, noisy,
unsynchronized, or unable to recover.
```

The system must therefore own:

- runtime health,
- service supervision,
- data freshness,
- state integrity,
- API/key readiness,
- model availability,
- dashboard visibility,
- Telegram escalation discipline,
- GitHub synchronization,
- operator documentation,
- safe self-recovery.

---

## 2. Separation of Strategy Domains

`TRADING_STRATEGY.md`

- Indodax trading logic,
- Polymarket trading logic,
- pump lifecycle,
- event probability,
- RiskGate,
- capital commander,
- executor behavior,
- daily GREEN objective.

`SYSTEM_STRATEGY.md`

- server health,
- systemd/service lifecycle,
- telemetry,
- storage cleanup,
- AI/toolchain management,
- dashboard/control plane,
- Telegram reporting discipline,
- GitHub/deployment workflow,
- documentation inventory,
- self-healing.

Rule:

```text
Trading strategy decides how money moves.
System strategy ensures the machine can safely decide and act.
```

---

## 3. Runtime Source of Truth

Systemd is the runtime source of truth on Batam.

Canonical services:

- `kibot-master`
- `kibot-scanner`
- `kibot-executor`
- `kibot-executor-polymarket`
- `kibot-ai-scout`
- `kibot-dashboard`
- `kibot-janitor`
- `ollama`
- `redis-server`

Rules:

- No duplicate legacy services.
- No hidden helper daemons unless documented.
- Every runtime service must have a purpose, owner, health check, and log path.
- `bin/kibotctl` is the preferred operator entrypoint.

Expected operator commands:

```bash
bin/kibotctl status
bin/kibotctl doctor
bin/kibotctl restart
bin/kibotctl sync-models
bin/kibotctl toolchain
```

---

## 4. Health Model

KiBot must continuously know whether it is:

- `HEALTHY`
- `DEGRADED`
- `RECOVERING`
- `BLIND`
- `UNSAFE`

### 4.1 HEALTHY

All required services active, telemetry fresh, APIs reachable, state files valid,
disk/RAM safe, dashboard available.

### 4.2 DEGRADED

One non-critical subsystem is impaired but trading can continue with reduced
confidence.

Examples:

- one AI provider down,
- web search provider rate-limited,
- dashboard stale but core trading active,
- one scanner source unavailable.

### 4.3 RECOVERING

System detected an issue and is actively trying to fix it.

Examples:

- restarting service,
- vacuuming logs,
- rebuilding state cache,
- resetting expired AI cooldown.

### 4.4 BLIND

System lacks enough data to make safe decisions.

Examples:

- balances stale,
- orderbook unavailable,
- Polymarket wallet unknown,
- telemetry snapshot stale,
- Redis unreachable.

Trading should pause or reduce to safe mode.

### 4.5 UNSAFE

System must block live trading.

Examples:

- live balance cannot be verified,
- executor cannot reconcile open positions,
- disk critical and unrecovered,
- corrupted active trade state,
- API auth failure for active venue,
- daily loss cap state unreadable.

---

## 5. Self-Healing Protocol

Every recoverable issue follows this ladder:

1. Detect.
2. Classify severity.
3. Record event.
4. Attempt safe recovery.
5. Re-check.
6. Degrade trading if needed.
7. Escalate to Telegram only if unrecovered or dangerous.

Recovery actions may include:

- restart service,
- reload systemd daemon,
- restart Redis/Ollama,
- clean safe logs/cache,
- rebuild telemetry snapshot,
- reset expired AI provider cooldown,
- rotate dashboard/event logs,
- refresh model availability,
- quarantine corrupted non-critical state.

Forbidden automatic actions:

- deleting secrets,
- deleting trading state without backup,
- force-resetting git,
- disabling live trading silently without logging,
- changing wallet/API keys,
- removing active positions without reconciliation.

---

## 6. Disk and Storage Strategy

Disk must never again reach critical fullness due to nested repos, logs, caches,
or model bloat.

### 6.1 Disk Thresholds

| Usage | State | Action |
|---|---|---|
| `<75%` | OK | normal |
| `75-85%` | Watch | log warning |
| `85-92%` | Clean | safe cleanup |
| `92-97%` | Recovering | aggressive cleanup, no big installs |
| `>97%` | Unsafe | block model pulls and alert if unrecovered |

### 6.2 Safe Cleanup Targets

- old logs,
- rotated journal logs,
- Python bytecode,
- pip/npm/browser caches,
- orphan temp files,
- nested KiBot repos,
- stale dashboard logs,
- stale AI cache,
- orphan Ollama blobs only when safely detected.

### 6.3 Protected Paths

Never auto-delete:

- `.env`,
- `.env.kiv`,
- wallet/key material,
- `state/active_trades.json`,
- `state/risk_state.json`,
- `state/learning_state.json`,
- `state/active_strategy.json`,
- order history,
- decision journal,
- server inventory.

---

## 7. State Integrity Strategy

State files are operational memory.

Critical state:

- active trades,
- risk state,
- daily state,
- learning state,
- active strategy,
- telemetry snapshot,
- decision journal,
- order tracker,
- Polymarket positions,
- AI provider state.

Rules:

- Writes should be atomic where possible.
- Critical state should be backed up before migration.
- Corrupt state should be quarantined, not overwritten silently.
- State schema changes must be documented.
- Dashboard should show state age and health.

---

## 8. API and Credential Readiness

KiBot must know which APIs are usable, rate-limited, expired, missing, or
misconfigured.

Required credential categories:

- Indodax trading,
- Telegram notification,
- Polymarket wallet/private key,
- Polymarket CLOB/API credentials,
- AI providers,
- web search/news providers,
- optional tooling providers.

Credential rules:

- Secrets never committed.
- `.env` protected with strict permissions.
- Missing optional keys degrade capability, not core runtime.
- Missing venue trading keys block that venue only.
- Auth failures should cool down provider and surface in dashboard.

---

## 9. AI and Model Strategy

Local AI and external providers are system resources.

### 9.1 Ollama

Ollama must be monitored for:

- service health,
- loaded models,
- RAM usage,
- API response,
- model availability,
- disk impact.

Model policy:

- small fast model for watchman/system checks,
- medium model for council reasoning,
- larger model only if disk/RAM allow,
- no large model pull if disk below safe threshold.

### 9.2 External AI Providers

Provider state should track:

- last success,
- last failure,
- rate limit,
- auth failure,
- cooldown until,
- average latency,
- role suitability.

Rules:

- 401 means auth failure, not temporary model weakness.
- 429 means cooldown/rate-limit.
- Provider selection should be role-aware.
- Local Ollama remains fallback when external providers fail.

---

## 10. Online Intelligence Strategy

Search/news/scrape providers are intelligence inputs, not trading authorities.

System must track health for:

- Tavily,
- Serper,
- DuckDuckGo/DDGS,
- Jina,
- Finnhub,
- GDELT,
- Brave if configured,
- CryptoPanic if configured,
- Polymarket APIs,
- Indodax APIs.

Rules:

- No single online source should override market structure.
- Contradictory sources reduce confidence.
- Stale web evidence must be labeled stale.
- Source failures should be visible but not spam Telegram.

---

## 11. Dashboard / Control Plane Strategy

Dashboard is the operator's cockpit.

It must answer:

- Is KiBot alive?
- Is KiBot trading?
- Does KiBot know current balances?
- What is KiBot thinking?
- What did KiBot reject and why?
- What is broken?
- What can self-recover?
- What needs operator help?

Required panels:

- system health,
- service graph,
- Capital Commander mode,
- Indodax ledger,
- Polymarket ledger,
- candidate leaderboard,
- rejected candidates,
- RiskGate reason,
- council role votes,
- what-if tree,
- source health,
- daily GREEN status,
- midnight report preview,
- self-healing events.

Dashboard may be rich and verbose. Telegram must not.

---

## 12. Telegram Strategy

Telegram is a scarce escalation channel.

Allowed messages:

- midnight daily report,
- unrecovered critical failure,
- live trading blocked due to unsafe state,
- executor cannot exit active position,
- credential/wallet failure,
- disk/RAM critical after recovery failed,
- daily loss cap hit.

Forbidden messages:

- every scanner signal,
- every council wait,
- routine health OK spam,
- repeated same warning without state change,
- verbose logs.

Telegram report should be concise, actionable, and no more than necessary.

---

## 13. GitHub and Deployment Strategy

GitHub is the durable source of repo truth.

Rules:

- Local and server repo should stay in sync after significant changes.
- Runtime state and secrets are never committed.
- README and inventory must be updated after server/tooling changes.
- Commits should be descriptive.
- Server deploys should be verified by compile + service health check.
- If server differs from GitHub, dashboard/inventory should mention drift.

Deployment flow:

```text
local edit
→ compile/test
→ commit
→ push GitHub
→ deploy/sync Batam
→ restart affected services
→ verify health
→ update inventory if needed
```

---

## 14. Tooling Strategy

Server-side tools are useful, but not runtime dependencies.

Tools:

- `aider` for targeted code edits,
- `gh` for GitHub operations,
- `copilot` as assistant/tooling only,
- `pipx` for isolated CLI installs,
- `bin/kibotctl` as operator entrypoint.

Rules:

- Tool failure must not break trading runtime.
- Tool installs must not fill disk.
- Tool versions should be recorded in inventory when important.

---

## 15. Documentation and Inventory Strategy

Docs are operational memory for future agents.

Required docs:

- `README.md`,
- `AGENTS.md`,
- `Core/Intelligence/README.md`,
- `Core/Intelligence/SERVER_INVENTORY.md`,
- `Core/Intelligence/strategy/TRADING_STRATEGY.md`,
- `Core/Intelligence/strategy/SYSTEM_STRATEGY.md`.

Docs must record:

- active services,
- ports,
- installed models,
- key APIs present/missing,
- websearch tools,
- server-only installs,
- runtime strategy state,
- known limitations,
- operator commands.

---

## 16. Security and Secret Strategy

Security baseline:

- secrets never committed,
- SSH keys restricted,
- `.env` chmod 600,
- private keys only in protected env/vault path,
- dashboard should not expose secrets,
- Telegram messages should not leak keys,
- logs should mask sensitive values,
- GitHub push must check ignored secrets.

Trading-specific security:

- venue private keys are high risk,
- Polymarket private key exposure means wallet compromise,
- Indodax API secret exposure means account compromise,
- any secret leak must trigger key rotation plan.

---

## 17. Mobile / APK Integration Strategy

KiBot mobile app should be a control/view layer, not a separate brain.

Mobile should display:

- live health,
- balances,
- daily GREEN state,
- active positions,
- system alerts,
- dashboard URL/status,
- manual read-only diagnostics.

Mobile should avoid:

- duplicating trading logic,
- storing secrets unnecessarily,
- bypassing RiskGate/Council,
- sending noisy notifications outside Telegram policy.

---

## 18. Failure Mode Playbooks

### 18.1 Disk Critical

1. Stop large installs/model pulls.
2. Run safe cleanup.
3. Check nested repos.
4. Vacuum logs.
5. Verify disk.
6. Alert only if unrecovered.

### 18.2 Service Down

1. Check systemd.
2. Check journal.
3. Restart service.
4. Re-check port/API.
5. Degrade trading if core service stays down.

### 18.3 Balance Blind

1. Stop new entries.
2. Re-auth venue API.
3. Check wallet/API response.
4. Rebuild telemetry.
5. Alert if unresolved.

### 18.4 AI Blind

1. Use local fallback.
2. Cool down failing provider.
3. Reduce reliance on online evidence.
4. Continue only if deterministic evidence is enough.

### 18.5 Dashboard Down

1. Trading can continue if core telemetry is healthy.
2. Restart dashboard.
3. Alert only if dashboard down plus telemetry blind.

---

## 19. System Maturity Target

KiBot system is considered mature when it can:

- keep services alive,
- detect and recover common failures,
- protect disk/state/secrets,
- know API/model/source health,
- show full dashboard observability,
- report daily without spam,
- sync GitHub/server state,
- document server-only reality,
- degrade trading safely when blind,
- escalate only when operator help is truly needed.

Final doctrine:

```text
KiBot should not require constant babysitting.
It should operate, observe itself, repair what is safe to repair,
explain what it cannot fix, and keep the operator informed without noise.
```

---

## 20. Governance and Authority Model

KiBot must know which parts of the system may be changed automatically and which
parts require operator awareness.

### 20.1 Authority Levels

`READ_ONLY`

- inspect logs,
- read status,
- read dashboard/API,
- read non-secret config,
- summarize issues.

`SAFE_RUNTIME`

- restart known systemd service,
- vacuum logs,
- clear safe cache,
- reset expired AI cooldown,
- regenerate telemetry,
- run doctor checks.

`CONFIG_CHANGE`

- edit non-secret runtime config,
- update strategy JSON,
- update dashboard settings,
- change thresholds.

`CODE_CHANGE`

- edit repository code,
- run tests,
- commit,
- push,
- deploy to server.

`HIGH_RISK`

- change secrets,
- change wallet/private keys,
- change live trading gate,
- delete state,
- force close positions,
- reboot server,
- alter firewall/SSH.

Rules:

- AI agents may operate in `READ_ONLY`, `SAFE_RUNTIME`, `CONFIG_CHANGE`, and
  `CODE_CHANGE` when requested or when clearly needed for system health.
- `HIGH_RISK` actions must be documented and should only happen when the risk
  of not acting is higher than acting.
- Secrets must never be printed, committed, or copied into docs.

### 20.2 Runtime vs Repository Changes

Runtime temporary fixes are allowed for emergency recovery, but permanent fixes
must be reflected in GitHub when they affect code, docs, config templates, or
operator workflow.

Rule:

```text
If a future agent needs to know it, document it.
If the server needs it after reboot, commit it or record it in inventory.
```

---

## 21. Change Management and Deployment

Every meaningful change should follow a lightweight release discipline.

### 21.1 Change Classes

`DOC_ONLY`

- markdown docs,
- inventory updates,
- comments.

`LOW_RISK_CODE`

- dashboard display,
- logging,
- report formatting,
- read-only diagnostics.

`RUNTIME_LOGIC`

- scanner,
- council,
- RiskGate,
- executor,
- state handling,
- notifier behavior.

`LIVE_TRADING_CRITICAL`

- order placement,
- sell/exit logic,
- wallet/API credentials,
- live trading gate,
- hard stop behavior.

### 21.2 Pre-Deploy Checklist

Before deploy:

- check git status,
- review diff,
- run syntax/compile checks,
- run targeted tests or smoke scripts,
- ensure secrets are ignored,
- check disk space,
- know which services need restart.

### 21.3 Post-Deploy Checklist

After deploy:

- restart affected services,
- verify systemd active,
- verify relevant ports,
- verify dashboard/API,
- verify logs for new errors,
- verify strategy/state if changed,
- update docs/inventory if needed.

### 21.4 Rollback Plan

Rollback options:

1. Revert config value.
2. Redeploy previous Git commit.
3. Disable affected feature flag.
4. Restart service.
5. Stop live trading gate if execution safety is uncertain.

Rollback must avoid deleting live state unless state itself is proven corrupt.

---

## 22. Disaster Recovery Strategy

KiBot must be restorable if Batam breaks.

### 22.1 Backup Classes

Critical:

- `.env` / vault material,
- active trades,
- risk state,
- active strategy,
- order tracker,
- learning state,
- decision journal,
- server inventory.

Important:

- dashboard config,
- service files,
- cron jobs,
- toolchain inventory,
- Ollama model list.

Rebuildable:

- Python caches,
- pip/npm cache,
- Playwright cache,
- temporary logs,
- generated telemetry snapshots.

### 22.2 Restore Checklist

1. Provision Ubuntu server.
2. Install system packages.
3. Clone GitHub repo.
4. Restore `.env`/vault securely.
5. Restore critical `state/`.
6. Install Python packages.
7. Install/verify Ollama models.
8. Install systemd units.
9. Run `bin/kibotctl doctor`.
10. Verify dashboard.
11. Verify Indodax/Polymarket read-only connectivity.
12. Enable live trading only after readiness passes.

### 22.3 Total Server Loss

If Batam is unavailable:

- do not assume open positions are closed,
- query exchanges from replacement system or manual device,
- reconstruct positions from venue APIs,
- restore state only after reconciliation,
- keep live trading disabled until account reality matches state.

---

## 23. Observability SLO

KiBot needs service-level objectives for observability freshness.

### 23.1 Freshness Targets

| Signal | Target Freshness |
|---|---:|
| service heartbeat | `<30s` |
| scanner heartbeat | `<30s` |
| dashboard summary | `<10s` |
| Indodax balance | `<2m` |
| Polymarket balance | `<5m` |
| active trades state | immediate on change |
| orderbook used for entry | `<10s` |
| telemetry snapshot | `<30s` |
| daily context | `<60s` |
| world model | `<30m` |

If data exceeds freshness limit, dashboard must mark it stale.

### 23.2 Blindness Rules

Trading should degrade when:

- balance data stale,
- orderbook stale,
- telemetry blind,
- active trade state uncertain,
- venue API unreachable,
- executor state differs from wallet reality.

---

## 24. Data Retention Policy

KiBot should retain enough history to learn while preventing disk bloat.

### 24.1 Suggested Retention

| Data | Retention |
|---|---:|
| raw logs | 3-7 days |
| compressed logs | 14-30 days |
| decision journal | 180 days or compressed |
| trade/order history | permanent unless archived |
| missed opportunity data | 180 days |
| scanner raw candidates | 30-90 days compressed |
| telemetry snapshots | 7-14 days |
| dashboard event stream | 7 days |
| AI cache | 1-7 days depending size |

### 24.2 Archive Rule

Learning-critical data should be compressed, not deleted, unless it is proven
duplicate or useless.

---

## 25. Configuration Management

Configuration must have clear ownership.

### 25.1 Config Sources

`.env`

- secrets,
- API keys,
- sensitive runtime switches.

`state/active_strategy.json`

- current live strategy state,
- runtime thresholds,
- mode information.

Repository config files:

- defaults,
- systemd templates,
- dashboard assets,
- non-secret settings.

Systemd environment:

- service launch behavior only.

### 25.2 Config Rules

- Secrets live only in protected env/vault.
- Strategy changes should be validated before service restart.
- Runtime overrides must be documented if they become permanent.
- Dashboard should show current effective mode.
- Config drift between GitHub and Batam should be visible.

---

## 26. Testing Strategy

Testing must cover both code correctness and live-readiness.

### 26.1 Test Layers

Unit tests:

- pure logic,
- parsers,
- scoring,
- state helpers.

Integration tests:

- Indodax read-only API,
- Polymarket read-only API,
- Redis,
- Ollama,
- dashboard API.

Smoke tests:

- service active,
- import/compile,
- dashboard reachable,
- UDP/TCP ports,
- sample scanner run,
- RiskGate known-pass/known-reject.

Dry-run trading tests:

- simulate candidate,
- build council mandate,
- run RiskGate,
- run pre-trade simulation,
- stop before real order.

### 26.2 Required Tests Before Live-Critical Deploy

- compile changed Python files,
- RiskGate reject tests,
- executor no-raw-signal test,
- balance read test,
- active state load test,
- dashboard summary test,
- service restart verification.

---

## 27. Security Hardening

Security must protect server access, dashboard exposure, and trading keys.

### 27.1 SSH

- private key permissions must stay strict,
- no SSH key committed accidentally,
- server access paths documented but secrets protected,
- rotate access if key exposure suspected.

### 27.2 Dashboard

Dashboard must not expose:

- API keys,
- private keys,
- full `.env`,
- auth headers,
- wallet private material.

If dashboard is public, future hardening should include auth, IP restriction, or
VPN/tunnel access.

### 27.3 Secret Rotation

Rotate secrets if:

- `.env` leaked,
- private key printed,
- git accidentally tracked secret,
- unknown login/access detected,
- provider reports suspicious activity.

### 27.4 Incident Response

If secret compromise suspected:

1. Disable live trading.
2. Rotate affected keys.
3. Revoke old credentials.
4. Check logs for unauthorized use.
5. Update inventory with incident note.
6. Restart affected services.

---

## 28. Dependency and Package Management

Dependencies must be intentional.

### 28.1 Python Packages

- record critical packages in inventory,
- avoid unnecessary global installs,
- prefer pinned requirements where possible,
- test imports after install,
- do not install large packages when disk is low.

### 28.2 System Packages

- record non-default packages,
- avoid removing packages used by system services,
- run apt cleanup after major installs,
- document TA-Lib/native library status.

### 28.3 Ollama Models

- model list must be documented,
- model pulls require disk check,
- remove unused large models only after confirming no role uses them,
- map models to council/system roles.

---

## 29. Resource Scheduling

Server resources are finite and must be scheduled.

### 29.1 Priorities

Highest:

- executors,
- risk/state reconciliation,
- balance reads,
- active exit management.

Medium:

- scanner,
- council,
- dashboard,
- AI scout.

Lower:

- deep research,
- model pulls,
- log compression,
- large backfills,
- GitHub sync.

### 29.2 Heavy Work Windows

Heavy work should avoid:

- active trade exit windows,
- midnight report window,
- disk pressure,
- RAM pressure,
- live API instability.

---

## 30. Human Override Protocol

Operator override must be explicit and logged.

Override types:

- pause live trading,
- resume live trading,
- force status report,
- force service restart,
- emergency stop,
- manual close request,
- config override,
- dashboard-only command.

Rules:

- every override creates an audit entry,
- trading override should update dashboard,
- emergency stop must prioritize preventing new entries,
- manual close still goes through executor safety where possible.

---

## 31. Server Migration Strategy

Migration must be boring and repeatable.

### 31.1 Migration Checklist

- clone repo,
- restore secrets,
- restore state,
- install dependencies,
- install systemd units,
- sync Ollama models,
- run doctor,
- run read-only exchange tests,
- validate dashboard,
- validate Telegram,
- only then enable live trading.

### 31.2 Mobile/API Update

If server IP changes:

- update dashboard/API endpoint,
- update APK config,
- update docs/inventory,
- test phone access,
- verify no old endpoint is still assumed by runtime.

---

## 32. APK / Mobile Release Strategy

Mobile app should follow release discipline.

Required:

- endpoint config,
- version display,
- compatibility with dashboard API,
- crash logging,
- read-only diagnostics,
- no duplicated trading brain,
- no secrets stored unless absolutely required.

Mobile should be a cockpit, not a second executor.

---

## 33. Incident Postmortem Loop

Every serious system failure should produce a small postmortem.

Postmortem fields:

```json
{
  "incident_time": "...",
  "impact": "...",
  "root_cause": "...",
  "detection": "...",
  "recovery_action": "...",
  "what_prevented_worse": "...",
  "what_to_fix": [],
  "owner": "system"
}
```

Postmortems should feed `SYSTEM_STRATEGY.md`, README, or code changes when they
reveal a repeatable weakness.

---

## 34. Autonomous Development Agent Policy

Codex, Aider, Copilot, and other agents must follow the same discipline.

Rules:

- read `AGENTS.md`,
- never commit secrets,
- avoid duplicate services,
- use `bin/kibotctl` where useful,
- update docs/inventory after meaningful server changes,
- compile/test before deploy,
- sync GitHub after completed changes,
- do not revert user changes without instruction,
- do not silently change live trading gates,
- record server-only installs or state changes.

Agent changes must be explainable to the next agent.

---

## 35. Final System Strategy Closure

System strategy is considered complete when KiBot can answer:

- what is running,
- what is broken,
- what was changed,
- what can self-recover,
- what needs the operator,
- what data is stale,
- what secrets are missing,
- what services are canonical,
- what version is deployed,
- what state is protected,
- how to restore from failure,
- how to avoid repeating incidents.

Final doctrine:

```text
The system must be boringly reliable so the trading brain can be intelligently aggressive.
```

---

## 36. Current Autonomy Maturity Baseline

This section records the honest current maturity estimate so future work does
not confuse strategy completeness with runtime autonomy.

### 36.1 Current Estimated Scores

| Dimension | Blueprint Maturity | Runtime Maturity | Notes |
|---|---:|---:|---|
| Trading intelligence | 95-98% | 60-70% | Strategy is strong; runtime still needs full implementation of every contract |
| System autonomy | 90-95% | 45-55% | System strategy is broad; runtime self-healing is partial |
| Server self-maintenance | 85-90% | 50-60% | Disk/service checks exist, but SLO/backup/rollback are incomplete |
| AI/tool orchestration | 80-85% | 50-60% | Providers and Ollama exist; role-aware routing and cooldown are partial |
| Dashboard observability | 85-90% | 60-70% | Dashboard exists; system-brain panels still need deeper visibility |
| Telegram discipline | 85-90% | 60-70% | Policy exists; daily/system health summaries can be improved |
| Deployment/GitHub discipline | 80-90% | 55-65% | Manual agent workflow works; automated deployment guard is missing |
| Disaster recovery | 80-85% | 25-40% | Strategy exists; backup/restore automation is not complete |

Plain-language assessment:

```text
KiBot is already partially autonomous.
It can run, trade, observe, and recover some common problems.
But it is not yet a fully self-governing system.
The next upgrade is not more raw tooling; it is a stronger system brain.
```

### 36.2 Runtime Reality

Current runtime can already do some of this:

- run canonical systemd services,
- keep scanner/council/executor/dashboard alive,
- use Redis and Ollama,
- track balances and state,
- clean disk in some cases,
- cool down failing AI providers,
- expose dashboard health,
- send Telegram through throttled notifier,
- maintain GitHub/docs with agent help.

Current runtime does not yet fully do:

- automatic deployment rollback,
- complete state backup/restore,
- full SLO freshness enforcement,
- full incident postmortem generation,
- full config validation before service start,
- complete system-health severity routing,
- complete dashboard command layer,
- autonomous server migration,
- full mobile/APK release control.

### 36.3 What-If Coverage

Already covered in strategy:

- disk full,
- service down,
- balance blind,
- AI provider failure,
- dashboard down,
- server migration,
- API key failure,
- Telegram spam,
- state corruption,
- GitHub/server drift,
- unsafe live trading,
- executor cannot exit,
- stale data,
- credential leak,
- package/model bloat,
- runtime config drift,
- disaster recovery,
- agent automation mistakes.

Still needs runtime modules:

- `system_commander.py`,
- `service_slo_monitor.py`,
- `state_backup.py`,
- `config_validator.py`,
- `incident_postmortem.py`,
- `deployment_guard.py`,
- dashboard system-brain panels.

### 36.4 Server Adaptation Maturity

Current server adaptation estimate:

```text
50-60% runtime maturity.
```

Already adapts to:

- some service failures,
- disk/log pressure,
- AI provider cooldown,
- dashboard status,
- Redis/Ollama status,
- API/source availability in some modules.

Needs stronger adaptation:

- convert all health into `HEALTHY/DEGRADED/RECOVERING/BLIND/UNSAFE`,
- enforce data freshness SLO,
- trigger safe degradation automatically,
- distinguish recoverable vs operator-required failures,
- backup state before risky changes,
- validate config before restart,
- explain recovery attempts in dashboard.

### 36.5 Control Maturity

Current control estimate:

```text
55-65% runtime control.
```

Current controlled areas:

- systemd services,
- scanner/council/executor/dashboard,
- trading strategy state,
- RiskGate,
- Telegram path,
- disk cleanup,
- AI provider cooldown,
- docs/GitHub through agent workflow.

Missing central control:

- one `System Commander` coordinating non-trading recovery,
- deployment controller,
- config validator,
- backup/restore controller,
- incident/postmortem automation,
- dashboard command layer for safe pause/recover/report actions,
- mobile/APK sync controller.

### 36.6 Installation and Tooling Assessment

Current installed capability is enough for the next stage.

Do not add heavy installations blindly. The priority is to build better system
modules using existing tools.

Already useful:

- Ollama,
- Redis,
- systemd,
- Indodax API,
- Polymarket API/wallet baseline,
- Telegram,
- Tavily/Serper/DDGS/Jina/Finnhub/GDELT style intelligence sources,
- external AI providers,
- Aider/GitHub/Copilot as development tools,
- dashboard,
- `bin/kibotctl`.

Possible future additions:

- SQLite-backed warehouse if JSONL becomes insufficient,
- backup/sync tool such as `rclone` if off-server backup is desired,
- dashboard auth/reverse proxy if exposure becomes sensitive,
- Prometheus/node-exporter only if internal telemetry becomes insufficient.

Current recommendation:

```text
Do not add big installations first.
Build the system brain first.
```

### 36.7 Next System Modules To Build

Priority order:

1. `System Commander`
2. `Service SLO Monitor`
3. `State Backup + Restore`
4. `Config Validator`
5. `Incident Postmortem Logger`
6. `Deployment Guard`
7. Dashboard system-brain panel
8. Telegram system-health summary inside midnight report
9. GitHub/server drift detector
10. Mobile/API endpoint health bridge

Expected improvement:

```text
Current runtime autonomy: ~45-55%.
After these modules: ~75-85%.
```

---

## 37. Inventory Utilization Strategy

Server inventory is not only documentation. It must become a runtime utilization
map.

Current reality:

```text
Many capabilities are installed and documented, but not all are fully
orchestrated by the system yet.
```

Estimated current utilization:

| Inventory Area | Current Utilization | Notes |
|---|---:|---|
| Core trading services | 80-85% | Services active and used |
| Ollama models | 60-70% | Models exist; role routing not fully explicit |
| External AI providers | 50-65% | Fallbacks exist; provider-role scoring incomplete |
| Web/search intelligence | 55-70% | Sources exist; source health/evidence mesh incomplete |
| Redis/state | 70-80% | Used, but state SLO/backup not complete |
| Dashboard | 65-75% | Good control plane, but not full system-brain visibility |
| Telegram | ~70% | Throttled, but system-health summary can improve |
| GitHub/aider/copilot/tooling | 40-55% | Available, but not autonomous workflow yet |
| Janitor/self-healing | 50-60% | Some recovery exists; no central System Commander yet |
| Polymarket runtime | 35-50% | Executor exists; advanced event intelligence incomplete |
| System strategy runtime | 45-55% | Strategy strong; implementation incomplete |

Rule:

```text
Every server inventory item must eventually answer:
installed? active? used by what? last checked? healthy? replaceable?
```

### 37.1 Inventory Utilization Matrix

Every inventory item should be tracked with:

```json
{
  "name": "deepseek-r1:7b",
  "type": "ollama_model",
  "installed": true,
  "active": false,
  "used_by": ["deep council", "system reasoning"],
  "last_verified": "YYYY-MM-DDTHH:MM:SSZ",
  "health": "OK|STALE|BROKEN|UNUSED",
  "notes": "heavy reasoning; use only when RAM/disk safe"
}
```

Dashboard should surface items with:

- installed but unused,
- configured but failing,
- missing but referenced,
- active but undocumented,
- server-only but not in inventory.

### 37.2 Model-to-Agent Routing Matrix

Ollama models must be explicitly mapped.

Suggested map:

| Role | Preferred Model | Fallback | Notes |
|---|---|---|---|
| Watchman / fast status | `qwen2.5:0.5b` | `qwen2.5:1.5b` | Fast, cheap, always available |
| Default Council | `qwen2.5:1.5b` | `qwen2.5:3b` | Balanced reasoning |
| Deep Council / Antagonist | `deepseek-r1:7b` | `mistral:7b` | Heavy reasoning only when safe |
| Sentiment / language | `llama3.2:3b` | `mistral:7b` | News/sentiment synthesis |
| Code/System Repair | `qwen2.5-coder:3b` | external coding provider | For wrappers, diagnostics, refactors |
| RAG embeddings | `nomic-embed-text` | none | Embedding only |

Rules:

- Heavy models should not run during RAM pressure.
- Model pulls require disk safety.
- If a model is listed in inventory but unused, either assign a role or remove it later.
- Dashboard should show model-role mapping and last use.

### 37.3 AI Provider Capability Matrix

External providers should be scored, not treated as equal.

Provider health fields:

```json
{
  "provider": "groq",
  "roles": ["fast reasoning", "summarization"],
  "last_success": "...",
  "last_failure": "...",
  "failure_type": "401|429|timeout|bad_json",
  "cooldown_until": "...",
  "avg_latency_ms": 1200,
  "quality_score": 0.78,
  "cost_risk": "LOW|MEDIUM|HIGH"
}
```

Routing goals:

- use fastest reliable provider for quick filtering,
- use stronger reasoning provider for high-risk council calls,
- use local Ollama when external providers fail,
- avoid repeatedly calling providers in active cooldown,
- show 401 as auth problem and 429 as rate-limit problem.

### 37.4 Source Health and Evidence Mesh

Web/search/news sources should become an evidence mesh.

Each source should report:

- configured,
- reachable,
- last success,
- last failure,
- rate limit,
- latency,
- result count,
- reliability score,
- source category.

Sources:

- Tavily,
- Serper,
- DuckDuckGo/DDGS,
- Jina,
- Finnhub,
- GDELT,
- Brave,
- CryptoPanic,
- Polymarket APIs,
- Indodax APIs.

Evidence rules:

- no single source decides a trade,
- source contradiction lowers confidence,
- stale evidence lowers confidence,
- official/primary sources outrank social/search aggregation,
- source health must be visible in dashboard.

### 37.5 Toolchain Utilization Policy

Tooling installed on server should have a defined purpose.

`gh`

- inspect repo,
- verify auth,
- support publish/sync workflows.

`aider`

- targeted code edits,
- local refactor assistance,
- never touch secrets.

`copilot`

- assistant/tooling only,
- not runtime dependency.

`bin/kibotctl`

- preferred operator interface,
- should expose status, doctor, tools, restart, logs, model sync.

Rules:

- toolchain failure must not affect trading runtime,
- tool versions/status should appear in inventory,
- dashboard may show toolchain readiness but should not depend on it.

### 37.6 Server Drift Detection

The server must detect drift between:

- GitHub HEAD,
- local server HEAD,
- working tree changes,
- runtime state,
- systemd unit files,
- strategy docs,
- dashboard assets.

Drift states:

`SYNCED`

- server HEAD matches GitHub and working tree clean except ignored state/logs.

`RUNTIME_DIRTY`

- server has local code/doc changes not committed.

`STATE_ONLY`

- only ignored runtime state/logs changed.

`DANGEROUS_DRIFT`

- service files, executor, RiskGate, secrets, or live strategy changed without docs/commit.

Dashboard should show drift state.

### 37.7 System Commander Runtime Contract

System Commander is the missing central control layer.

Responsibilities:

- read inventory utilization,
- read system health,
- classify health state,
- trigger safe recovery,
- block/degrade trading if blind,
- track provider/source health,
- track model health,
- track GitHub/server drift,
- trigger backups,
- write incident records,
- feed dashboard,
- escalate to Telegram only if needed.

Output:

```json
{
  "system_state": "HEALTHY|DEGRADED|RECOVERING|BLIND|UNSAFE",
  "inventory_utilization_score": 0.68,
  "services": {},
  "models": {},
  "providers": {},
  "sources": {},
  "drift": "SYNCED",
  "self_healing_actions": [],
  "operator_required": false
}
```

### 37.8 Dashboard Inventory Usage Panel

Dashboard should show:

- installed models and assigned roles,
- active services and owners,
- API/source health,
- AI provider cooldowns,
- toolchain readiness,
- GitHub/server drift,
- backup status,
- config validation status,
- unused inventory items,
- missing runtime modules.

Goal:

```text
The operator should see not only what exists, but whether KiBot is actually using it.
```

### 37.9 Polymarket Runtime Gap Tracker

Polymarket should have explicit runtime gap tracking because it is currently the
least mature major subsystem.

Track:

- wallet health,
- USDC balance,
- CLOB auth health,
- market fetch health,
- orderbook health,
- position reconciliation,
- probability engine status,
- resolution parser status,
- liquidity simulator status,
- evidence bundle status,
- mark-to-market status.

Until all are implemented:

```text
Polymarket should remain controlled and conservative compared with Indodax.
```

### 37.10 Inventory Utilization Target

Target maturity:

```text
Inventory documentation: 95%+
Inventory runtime utilization: 80%+
Inventory dashboard visibility: 80%+
Inventory self-healing integration: 70%+
```

Current estimate:

```text
Inventory runtime utilization: 55-65%.
```

Next upgrade path:

1. Build Inventory Utilization Matrix.
2. Build Model-to-Agent Routing Matrix.
3. Build Provider Capability Matrix.
4. Build Source Health Evidence Mesh.
5. Build Server Drift Detector.
6. Build System Commander.
7. Add dashboard inventory usage panel.
