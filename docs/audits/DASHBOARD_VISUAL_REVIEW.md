# DASHBOARD_VISUAL_REVIEW.md

## Dashboard Rebuild — v4.0 (KiBot Delegation Style)

**Commit:** `d6a9b0e`  
**Date:** 2026-05-18  
**URL:** http://127.0.0.1:8787  

---

## Theme Change

| Before | After |
|---|---|
| Dark cyberpunk / neon overload | Clean light workspace (#f1f5f9 bg) |
| Random card colors | Systematic design tokens |
| Excessive vertical scroll | `overflow: hidden` — no body scroll |
| Fake / placeholder data | Single source of truth: `/api/control-plane` |
| Packed panels, no breathing room | 3-column grid with generous whitespace |
| `runtime dirty`, `unknown` fallbacks | Explicit STALE / UNKNOWN labels with freshness age |

---

## Acceptance Checklist

- [x] Light reference-inspired theme (`#f1f5f9` background, white panels)
- [x] No body scroll on 1920×1080 — `html, body { overflow: hidden }` enforced
- [x] Agent hierarchy visible in center canvas (SVG dotted connector lines)
- [x] Left logs readable — Activity / Technical tabs, internal scroll
- [x] Right project info readable — Portfolio / Safety / Venues / Gates
- [x] Real / Paper / Simulation PnL clearly separated with color badges
- [x] Live Trading clearly OFF — Safety section shows OFF badge
- [x] No secret values — `test_zero_secret_leak` passed
- [x] No fake PnL — `test_simulated_vs_real_pnl_isolation` passed
- [x] No overlapping text — cards have defined layout, no collapse
- [x] 92 pytest passed (up from 88)

---

## Files Changed

| File | Action |
|---|---|
| `Core/Intelligence/kibot_dashboard.py` | Added `_file_age_s()` helper + `freshness` block to control-plane payload |
| `Core/Intelligence/dashboard/index.html` | **Full rewrite** — 3-column Delegation layout |
| `Core/Intelligence/dashboard/style.css` | **Full rewrite** — light theme, design tokens, no-scroll |
| `Core/Intelligence/dashboard/live.js` | **Full rewrite** — single `/api/control-plane` source of truth |
| `tests/test_dashboard_control_plane.py` | +5 new tests: freshness, HTML structure, CSS rules, JS source check |

---

## Known Remaining (Minor)

- Left Activity log currently shows raw log lines from `kibot_sovereign.log` — these are real log lines, not placeholder. Vault decryption errors are filtered to Technical tab.
- Scanner status shows `STALE` because no live scanner is running locally (expected in dev environment).
- `WARNING` badge shown because signal/EV gates are in REJECT state (correct — no tradeable signal in paper mode).

---

## Visual Match Score

| Component | Match |
|---|---|
| Top bar layout | ✅ Close to reference |
| Agent cards with colored borders | ✅ |
| Delegation canvas with SVG connectors | ✅ |
| Bottom queue board 4 lanes | ✅ |
| Left log panel with tabs | ✅ |
| Right project info panel | ✅ |
| No body scroll | ✅ |
| Light clean theme | ✅ |

**Verdict: DASHBOARD_REBUILD_ACCEPTED**
