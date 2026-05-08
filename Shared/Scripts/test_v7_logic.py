import sys, os, json, time
from pathlib import Path

# Setup test environment
os.environ["SUPABASE_URL"] = ""  # disable sync
os.environ["KIBOT_STATE_DIR"] = "/tmp/kibot_test"
REPO_ROOT = Path(__file__).resolve().parents[2]
for rel in [
    "SERVER_BATAM/Core_Logic",
    "SERVER_BATAM/Indicators_Math",
    "SERVER_BATAM/Intelligence",
    "SERVER_BATAM/Support",
]:
    sys.path.insert(0, str(REPO_ROOT / rel))

test_state = Path("/tmp/kibot_test")
test_state.mkdir(parents=True, exist_ok=True)

# ─── Import test ───
from kibot_engine_v2 import (
    safe_float, calc_bollinger, calc_rsi, calc_volume_trend,
    compute_conviction, simulate_what_if, CascadeState,
    evaluate_exit, OpenPosition, TradeLogger, dual_scanner_agree,
    size_bucket_a, size_bucket_b
)
print("✅ Import OK")

# ─── safe_float (Indodax koma) ───
assert safe_float("1.234") == 1.234
assert safe_float("1,234") == 1.234
assert safe_float("") == 0.0
print("✅ safe_float OK")

# ─── Bollinger Band ───
closes = [100+i*0.5 for i in range(25)]
bb = calc_bollinger(closes)
assert bb is not None
assert bb["upper"] > bb["middle"] > bb["lower"]
print(f"✅ Bollinger OK: mid={bb['middle']:.1f}")

# ─── RSI ───
rsi_flat = calc_rsi([100]*20)
assert 45 <= rsi_flat <= 55, f"RSI flat harus ~50, got {rsi_flat}"
rsi_up = calc_rsi([100+i for i in range(20)])
assert rsi_up > 60, f"RSI uptrend harus >60, got {rsi_up}"
print(f"✅ RSI OK: flat={rsi_flat:.1f} up={rsi_up:.1f}")

# ─── Volume trend ───
vt_up   = calc_volume_trend([10,10,10,10,10,10,10,20,25,30])
vt_down = calc_volume_trend([30,25,20,10,10,10,10,5,4,3])
assert vt_up == "increasing", f"Expected increasing, got {vt_up}"
assert vt_down == "decreasing", f"Expected decreasing, got {vt_down}"
print("✅ Volume trend OK")

# ─── ConvictionScore: WHITEWHALE +100% harus BLOCK ───
ticker_ww = {"last":"218","buy":"216","sell":"220","high":"226","low":"108","vol_idr":"15700000000","open":"109"}
closes_ww = [218.0]*25
result_ww = compute_conviction("whitewhale_idr", ticker_ww, closes_ww, [932360]*25, 8_000_000_000)
assert not result_ww["allowed"], f"WHITEWHALE +100% harus BLOCK, got allowed={result_ww['allowed']}"
print(f"✅ WHITEWHALE +100% BLOCKED: {result_ww['reason']}")

# ─── ConvictionScore: koin EARLY phase ───
closes_early = [100 + i*0.3 for i in range(25)]
ticker_ok = {"last":"110","buy":"109","sell":"111","high":"130","low":"100","vol_idr":"2000000000","open":"105"}
result_ok = compute_conviction("test_idr", ticker_ok, closes_early, [1000000]*25, 1_500_000_000)
assert 0.0 <= result_ok["score"] <= 1.0, "Score harus 0-1"
print(f"✅ EARLY coin: score={result_ok['score']:.3f} phase={result_ok['phase']} allowed={result_ok['allowed']}")

# ─── What-If Engine ───
sim = simulate_what_if("br_idr", 10000, 0.02, 0.015, 0.05, 0.04, 0.55, 20)
assert sim["decision"] in ("ENTER","REDUCE","SKIP")
assert -0.5 <= sim["net_pct"] <= 0.5
print(f"✅ What-If BR: {sim['decision']} EV=Rp{sim['ev_idr']:.0f} RR={sim['rr']:.2f}")

# ─── CascadeState ───
cs = CascadeState()
# Reset to growth for test
cs.mode = "GROWTH"
cs.consecutive_losses = 0
cs.wins_today = 0
cs.daily_pnl_pct = 0.0
cs.on_loss(-0.01)
assert cs.mode == "CAUTION", f"1 loss → CAUTION, got {cs.mode}"
cs.on_loss(-0.015)
assert cs.mode == "DEFENSIVE", f"2 berturut → DEFENSIVE, got {cs.mode}"
cs.on_win(); cs.on_win()
assert cs.mode == "CAUTION", f"2 wins dari DEFENSIVE → CAUTION, got {cs.mode}"
cs.on_loss(-0.025)
assert cs.mode == "HARD_STOP", f"daily -2.5% → HARD_STOP, got {cs.mode}"
print(f"✅ CascadeState PASSED (G→C→D→C→HS)")

# ─── Size bucket A ───
sz_a = size_bucket_a(30000, 0.55, 0.03, 0.02, 1.0, "xrp_idr")
# For small balance 30k, 12% is 3.6k, so floor 10k should win.
assert sz_a == 10000, f"Expected floor 10000 for small balance, got {sz_a}"
print(f"✅ Size Bucket A: Rp{sz_a:,.0f} (floor hit ok)")

sz_b = size_bucket_b(30000, 5, 0.5, 0.04, 0.03, 1.0, "br_idr")
assert sz_b == 10000, f"Expected floor 10000 for small balance, got {sz_b}"
print(f"✅ Size Bucket B: Rp{sz_b:,.0f} (floor hit ok)")

# ─── Exit ladder ───
pos = OpenPosition("t1","br_idr","B",3000.0,10000.0,3.33,0.87,"EARLY","ord1",0.05,0.08,"2026-01-01T00:00:00")
ex1 = evaluate_exit(pos, 3090.0, 45, "stable", 0.87, -0.005, -0.5, 45, None)
assert ex1["action"] == "PARTIAL_EXIT" and ex1["pct"] == 0.30, f"TP +3%: expected PARTIAL_EXIT 30%, got {ex1}"
print(f"✅ Exit TP +3%: {ex1['action']} {ex1['pct']*100:.0f}% ({ex1['reason']})")

ex2 = evaluate_exit(pos, 3090.0, 45, "stable", 0.87, -0.025, -0.5, 10, None)
assert ex2["action"] == "EXIT_ALL", f"Daily -2.5%: expected EXIT_ALL, got {ex2['action']}"
print(f"✅ Exit daily -2.5%: {ex2['action']} ({ex2['reason']})")

ex3 = evaluate_exit(pos, 2910.0, 45, "stable", 0.87, -0.005, -0.5, 10, None)
assert ex3["action"] == "EXIT_ALL", f"Hard stop -3%: expected EXIT_ALL, got {ex3['action']}"
print(f"✅ Exit hard stop: {ex3['action']} ({ex3['reason']})")

# ─── TradeLogger ───
tl = TradeLogger()
tid = f"br{int(time.time())%10000}"
tl.record_entry(tid,"br_idr","B",3449.0,10000.0,0.87,"EARLY","GROWTH",0.05,0.04,"ord123")
result = tl.record_exit(tid, 3900.0, "TRAILING_STOP")
assert result is not None, "Exit tidak tercatat"
assert result["win"], f"Harusnya win (3449→3900), pnl={result.get('pnl_idr')}"
assert not tl.is_in_cooldown("br_idr"), "Win tidak boleh trigger cooldown"
print(f"✅ TradeLogger PASSED: pnl=Rp{result['pnl_idr']:+,.0f} ({result['pnl_pct']:+.2%})")

# ─── Cooldown setelah loss ───
tl2 = TradeLogger()
tid2 = f"xrp{int(time.time())%10000}"
tl2.record_entry(tid2,"xrp_idr","A",15000.0,10000.0,0.75,"MID","GROWTH",0.02,0.015,"")
tl2.record_exit(tid2, 14500.0, "HARD_STOP")
assert tl2.is_in_cooldown("xrp_idr"), "Setelah loss harus cooldown"
print("✅ Cooldown setelah loss PASSED")

print("\n" + "="*50)
print("✅ SEMUA 15 TEST PASSED")
print("="*50)
