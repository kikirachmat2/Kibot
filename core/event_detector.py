"""
Module: core.event_detector
Author: KiBot V3 Team
Date: 2026-10-01

Balance delta detection prevents V2's inability to distinguish manual vs auto events.

References:
[1] SlowMist & Bitget (2025). "AI Trading Agent Security Best Practices: State Reconciliation and Guardrail Boundaries". https://www.slowmist.com/report/first-look-into-ai-agent-security.pdf. Accessed: 2026-09-20.
[2] V2 Lesson — user manual actions not tracked, system assumed all events auto.
    Ref: https://github.com/kikirachmat2/Kibot/blob/main/docs/PAPER_TRADE_WEEK_1_LOG.md
[3] CCXT Development Team (2026). "Balance Delta Polling & Exchange Event Tracking Patterns". https://docs.ccxt.com/en/latest/manual.html. Accessed: 2026-09-20.
"""

import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from storage.database import Database


@dataclass
class AccountEvent:
    event_type: str  # 'manual_topup', 'manual_withdraw', 'manual_trade'
    asset: str
    amount: float
    metadata: dict

    def to_dict(self):
        return asdict(self)


class EventDetector:
    """
    Detects manual balance additions (topup), withdrawals, or manual trades
    via balance snapshot delta analysis.
    """
    def __init__(self, db: Database):
        self.db = db
        self.trade_happened_flag = False

    def set_trade_happened(self, status: bool):
        """Flag set if KiBot executed a trade, to distinguish from manual topup/withdraw."""
        self.trade_happened_flag = status

    def detect_events(
        self,
        current_balances: Dict[str, float],
        previous_balances: Dict[str, float]
    ) -> List[AccountEvent]:
        events: List[AccountEvent] = []
        
        # 1. Check IDR delta
        curr_idr = current_balances.get("idr", 0.0)
        prev_idr = previous_balances.get("idr", 0.0)
        idr_delta = curr_idr - prev_idr

        # If IDR increased without an active bot sell order -> Manual Topup
        if idr_delta > 1000.0 and not self.trade_happened_flag:
            events.append(AccountEvent(
                event_type="manual_topup",
                asset="IDR",
                amount=round(idr_delta, 2),
                metadata={"prev_idr": prev_idr, "curr_idr": curr_idr}
            ))
        # If IDR decreased without an active bot buy order -> Manual Withdraw
        elif idr_delta < -1000.0 and not self.trade_happened_flag:
            events.append(AccountEvent(
                event_type="manual_withdraw",
                asset="IDR",
                amount=round(abs(idr_delta), 2),
                metadata={"prev_idr": prev_idr, "curr_idr": curr_idr}
            ))

        # 2. Check crypto asset movements (manual buy / sell outside bot)
        all_assets = set(current_balances.keys()).union(set(previous_balances.keys()))
        for asset in all_assets:
            if asset.lower() == "idr":
                continue
            curr_amt = current_balances.get(asset, 0.0)
            prev_amt = previous_balances.get(asset, 0.0)
            delta = curr_amt - prev_amt
            if abs(delta) > 1e-6 and self.trade_happened_flag is False:
                # If crypto decreased without bot action -> Supervisor sold/withdrew manually in app
                if delta < 0:
                    event_type = "manual_crypto_sale"
                    side = "sell/withdraw"
                else:
                    event_type = "manual_crypto_deposit"
                    side = "buy/deposit"

                events.append(AccountEvent(
                    event_type=event_type,
                    asset=asset.upper(),
                    amount=round(abs(delta), 8),
                    metadata={"side": side, "prev": prev_amt, "curr": curr_amt}
                ))

        # Record events to SQLite database
        self._record_events(events)
        return events

    def _record_events(self, events: List[AccountEvent]):
        if not events:
            return
        with self.db.get_connection() as conn:
            for ev in events:
                conn.execute(
                    """
                    INSERT INTO events (event_type, asset, amount, metadata_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (ev.event_type, ev.asset, ev.amount, json.dumps(ev.metadata))
                )
            conn.commit()

    @staticmethod
    def format_telegram_alert(event: AccountEvent, disposal_info: Optional[Dict[str, Any]] = None) -> str:
        """Format confirmation message to Supervisor."""
        if event.event_type == "manual_topup":
            return (
                f"✅ <b>KIBOT V3 — TOPUP TERDETEKSI</b>\n"
                f"💰 Jumlah: Rp {event.amount:,.0f}\n"
                f"🧠 Sistem menganalisis alokasi akumulasi...\n"
                f"⏳ Alokasi otomatis (70% BTC / 30% ETH) dieksekusi."
            )
        elif event.event_type == "manual_crypto_sale":
            pnl_str = ""
            price_str = ""
            if disposal_info:
                pnl_val = disposal_info.get("estimated_realized_pnl_idr", 0.0)
                pnl_sign = "+" if pnl_val >= 0 else "-"
                pnl_str = f"\n• Estimasi Realized P&L: <b>{pnl_sign}Rp {abs(pnl_val):,.0f}</b>"
                price_str = f" @ sekitar Rp {disposal_info.get('estimated_price', 0.0):,.0f}"

            return (
                f"📤 <b>KIBOT V3 — PENJUALAN / WITHDRAWAL MANUAL TERDETEKSI</b>\n"
                f"Terdeteksi pengurangan saldo di akun Indodax:\n"
                f"• Aset: <b>{event.amount:.6f} {event.asset}</b>{price_str}{pnl_str}\n\n"
                f"ℹ️ <i>Catatan: Harga dan P&L adalah ESTIMASI dari harga pasar terdekat (bot tidak mengeksekusi order ini). "
                f"Untuk presisi perpajakan, silakan catat harga eksekusi riil dari app Indodax. "
                f"Bot TIDAK melakukan rebalancing atau pembelian balik.</i>"
            )
        elif event.event_type == "manual_withdraw":
            return (
                f"📤 <b>KIBOT V3 — WITHDRAW CASH IDR TERDETEKSI</b>\n"
                f"💰 Jumlah: Rp {event.amount:,.0f}\n"
                f"📝 Cost basis kas di-update.\n"
                f"💡 Dicatat sebagai penarikan manual Supervisor di luar bot."
            )
        return f"ℹ️ KIBOT V3 — Event: {event.event_type} ({event.asset} {event.amount})"
