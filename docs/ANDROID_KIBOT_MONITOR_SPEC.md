# KiBot Monitor Android App Spec

## Product Goal
KiBot Monitor is a lightweight operator app for watching live trading truth on Android without exposing secrets or trading controls.

It should be:
- glanceable,
- calm,
- Material 3 native,
- background-synced with WorkManager,
- able to recover after reboot,
- capable of a foreground notification when monitoring is continuous,
- and equipped with a 5x2 home-screen widget.

## Non-Goals
- No live order entry.
- No withdrawal.
- No bridge execution.
- No secret display.
- No profit guarantee messaging.

## Information Architecture
### Primary screens
1. Overview
   - runtime mode
   - total equity
   - realized / unrealized PnL
   - risk state
   - live truth freshness

2. Venues
   - Indodax status
   - Phantom status
   - per-venue equity
   - lock reason if any

3. Orders
   - recent fills
   - pending orders
   - rejected candidates
   - dust positions

4. Logs
   - exceptions only
   - trade summaries
   - recovery/restart events

5. Debug
   - last sync time
   - app state age
   - worker status
   - service status

## UI Rules
- Use Material 3 surfaces and cards.
- Use chips for venue state and runtime state.
- Use large readable numbers for equity and PnL.
- Keep operator language in Indonesian where it helps clarity.
- Use a bottom NavigationBar for compact devices.
- Prefer a single column layout on phones.
- Use split cards or list rows rather than heavy charts.

## Background Architecture
### WorkManager
- Use WorkManager for periodic sync of dashboard truth from the backend.
- Sync should persist across app restarts and device reboot.
- Use periodic work with a sensible cadence, and fallback retry with backoff.

### Foreground Service
- Use a foreground service for user-visible continuous monitoring.
- The notification should clearly say the app is monitoring live truth.
- If the app cannot monitor, it should say why.

### Widget
- Create a 5x2 information widget.
- Surface only:
  - runtime mode
  - total equity
  - net PnL
  - risk state
  - venue status
  - last exception
- Tapping the widget opens the app detail screen.

## Data Contract
The app should read the same canonical truth used by the web dashboard:
- `state/live_truth.json`
- `api/control-plane`

## Operator Copy
Safe copy examples:
- “Autonomous LIVE_ONLY runtime. Can trade when deterministic gates pass. No profit guarantee.”
- “Locked because Phantom env is missing.”
- “Waiting for deterministic gate.”

Avoid:
- “guaranteed profit”
- “auto cuan”
- “pasti profit”
- “paper”
- “mock”
- “shadow”

## Implementation Notes
- Base package can live under `android/KiBotMonitor/`.
- Recommended stack:
  - Kotlin
  - Jetpack Compose
  - Material 3
  - WorkManager
  - Glance for widget
  - Foreground service for monitoring
- Use a repository layer that reads the backend truth payload and maps it to UI state.

## Delivery Checklist
- [ ] App scaffold exists
- [ ] Material 3 theme applied
- [ ] Overview screen built
- [ ] Venue screen built
- [ ] Orders and Logs screens built
- [ ] Periodic sync worker built
- [ ] Foreground monitoring service built
- [ ] 5x2 widget built
- [ ] Debug APK builds on a machine with Android SDK
- [ ] APK installs on the connected Android device
