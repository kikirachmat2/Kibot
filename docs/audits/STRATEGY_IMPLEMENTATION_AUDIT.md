# Strategy Implementation Audit

Generated to separate strategy files that are runtime-connected from those that are documentation-only.

| Strategy/Module | File | Implemented | Connected to Runtime | Connected to Dashboard | Has Tests | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Indodax pump/microtrend strategy | `Core/Intelligence/indodax_microstructure.py`, `Core/Executors/Indodax/indodax_executor.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Lead-lag alpha | `Core/Intelligence/leadlag_alpha.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Market rotation | `Core/Intelligence/market_rotation.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Expected value gate | `Core/Intelligence/expected_value.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Signal quality | `Core/Intelligence/signal_quality.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Strategy scorecard | `Core/Intelligence/strategy_scorecard.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Punishment engine | `Core/Intelligence/punishment_engine.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Autonomous director | `Core/Intelligence/autonomous_director.py` | Yes | Yes | Yes | Yes | CONNECTED |
| RiskGate | `Core/risk_gate.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Capital Governor | `Core/Treasury/capital_governor.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Phantom Treasury | `Core/Treasury/phantom_treasury.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Phantom multichain controller | `Core/Treasury/phantom_multichain_controller.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Web3 scanner | `Core/Web3/web3_opportunity_scanner.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Web3 safety checker | `Core/Web3/web3_safety_checker.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Web3 quote router | `Core/Web3/web3_quote_router.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Web3 executor guard | `Core/Web3/web3_executor_guard.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Web3 exit daemon | `Core/Web3/web3_exit_daemon.py` | Yes | No | No | No | IMPLEMENTED_BUT_NOT_CONNECTED |
| Polymarket executor | `Core/Executors/Phantom/polymarket_executor.py` | Yes | Yes | Yes | Yes | CONNECTED |
| Dashboard control-plane | `Core/Intelligence/kibot_dashboard.py`, `Core/Intelligence/dashboard/` | Yes | Yes | Yes | Yes | CONNECTED |

## Notes

- Strategy files in `Core/Intelligence/strategy/` are used both as runtime policy references and dashboard sources.
- `web3_exit_daemon.py` exists as a safe exit loop, but it still needs a dedicated service activation and runtime integration before it is considered fully connected.
- This audit intentionally marks file-only or dashboard-only surfaces differently from runtime gates.
