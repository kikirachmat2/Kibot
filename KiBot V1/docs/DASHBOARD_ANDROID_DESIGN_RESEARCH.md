# KiBot Dashboard + Android Monitor Design Research

## Visual Direction
- Use a calm premium command-center style instead of a noisy crypto-casino look.
- Borrow the clarity of Linear, Vercel, Stripe, Grafana Cloud, Datadog, and TradingView, then soften it with Apple-style frosted glass and subtle glow accents.
- Keep motion minimal and functional: fresh data, active tabs, live state, and transition feedback should get the motion treatment, not every surface.
- Prefer shadcn-style card hierarchy: clear container surfaces, restrained borders, strong typography, and strong spacing discipline.
- Use Magic UI-style shimmer or glow only for live/freshness affordances, not as a global visual language.

## Layout Patterns
- A top navigation bar should define the current mode and let the operator jump between high-level sections.
- The primary content should be split into:
  - left activity/telemetry rail,
  - center workflow/topology area,
  - right truth/control rail.
- The graph/topology should live as a diagnostic surface, not the whole product.
- Tabs should control the main information architecture: Overview, Workflow, Venues, AI System, Orders, Logs, Debug.
- A premium dashboard should present a clear hierarchy:
  1. runtime/mode,
  2. equity and PnL,
  3. risk and blockers,
  4. readiness by venue,
  5. next action.

## Component Inventory
- 21st.dev component taxonomy is a good checklist for dashboard coverage:
  - cards
  - tabs
  - badges
  - tables
  - tooltips
  - scroll areas
  - navigation menus
  - background treatments
  - borders
  - number/stat components
  - AI/chat-style status components
- shadcn/ui is the right foundation for a composable operator dashboard:
  - sidebar / nav
  - cards
  - tables
  - badges
  - alerts
  - tooltips
  - sheets/drawers
  - dashboard blocks
- Suggested dashboard components:
  - Mode badge
  - Freshness badge
  - KPI strip
  - Readiness cards
  - Why-WAIT card
  - Next action card
  - Venue status table
  - Exceptions list
  - Trade summary table
  - Legacy debug accordion

## Motion Rules
- Motion.dev patterns to use:
  - layout animation for tab switching and panel reflow
  - stagger for card/list entry
  - hover/press feedback for tabs and cards
  - exit animation for dismissible panels
  - skeleton shimmer for loading states
- Motion should be subtle and fast:
  - 120-180ms for hover/press
  - 220-320ms for layout changes
  - spring easing for active status transitions
- Use animation to reduce uncertainty:
  - fresh data can pulse softly
  - stale data should desaturate or badge itself
  - live route badges can gently glow

## Dashboard Anti-Patterns
- Do not let the graph dominate the page.
- Do not mix live, paper, shadow, mock, canary, or soak wording in the same visible surface.
- Do not show blockers as generic red failure if orders are actually allowed.
- Do not hide the next autonomous action.
- Do not overload the screen with dense text without hierarchy.
- Do not make every card glow.
- Do not make crypto UI look like a meme exchange leaderboard.
- Do not put debug detail in the primary operator path.

## Android App Design Rules
- Use Material 3 and Compose as the base system.
- Use dynamic color where possible, but keep the palette restrained and readable.
- The Android app should prioritize:
  - glanceable health,
  - live/truth PnL,
  - venue readiness,
  - recent events,
  - emergency status,
  - last trade summary.
- Favor:
  - Surface/Card hierarchy
  - NavigationBar for compact screens
  - Chips for venue state
  - Alert cards for exceptions
  - Large readable numerals for equity / PnL
- Background work should use WorkManager for persistent sync.
- Continuous user-visible monitoring should use a foreground service with a clear notification.

## Widget Design Rules
- The widget must be glanceable, not scrollable.
- Keep it to 5x2 style information density:
  - runtime mode
  - total equity
  - daily PnL
  - risk state
  - venue status
  - last exception
- Tapping the widget should open the app detail view.
- Use concise labels and avoid long debug text.
- The widget is a snack; the app is the meal.

## Implementation Checklist
- [ ] Redesign web dashboard around clear section tabs and calm card hierarchy
- [ ] Reduce graph dominance and move detail into Workflow/Topology
- [ ] Add explicit Why-WAIT and Next Autonomous Action surfaces
- [ ] Replace legacy-looking wording and noisy red blockers
- [ ] Keep live freshness subtle but visible
- [ ] Build Android Monitor scaffold with Material 3
- [ ] Add WorkManager sync worker
- [ ] Add foreground monitoring service
- [ ] Add 5x2 widget
- [ ] Document operator rules and no-profit-guarantee language
- [ ] Validate dashboard with screenshot QA after rendering

## Source Notes
- 21st.dev: https://21st.dev/
- Magic UI: https://magicui.design/
- shadcn/ui: https://ui.shadcn.com/
- Motion: https://motion.dev/
- Material 3: https://m3.material.io/ and https://developer.android.com/develop/ui/compose/designsystems/material3
- Android background work: https://developer.android.com/develop/background-work/background-tasks/persistent
- Android foreground services: https://developer.android.com/develop/background-work/services/fgs
- Android widgets: https://developer.android.com/develop/ui/views/appwidgets/overview
