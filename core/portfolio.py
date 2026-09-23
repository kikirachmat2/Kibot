"""
Module: core.portfolio
Author: KiBot V3 Team
Date: 2026-10-01

Weighted average cost basis prevents V2's equity double-count bug.

References:
[1] CFA Institute (2024). "Global Investment Performance Standards (GIPS) & Cost Basis Methodologies for Multi-Asset Portfolios". https://www.cfainstitute.org/en/ethics-standards/codes/gips-standards. Accessed: 2026-09-20.
[2] V2 Audit — equity reported as Rp 199.975 when initial Rp 100.000 karena cash_idr tidak di-restore dengan benar saat restart.
    Ref: https://github.com/kikirachmat2/Kibot/blob/main/docs/SECURITY_INCIDENT_20260920.md
[3] Indodax Trading Operations (2026). "Official IDR Market Pro Fee Schedule: Maker 0.1111%, Taker 0.2111%, PPh 0.21%".
"""

import json
from dataclasses import dataclass
from typing import Dict, Optional, Any
from storage.database import Database


@dataclass
class Position:
    asset: str
    amount: float
    cost_basis_idr: float       # Average purchase price per unit (weighted)
    total_invested_idr: float   # Cumulative net IDR injected into this asset


class PortfolioTracker:
    """
    Maintains persistent portfolio state, positions, cost-basis calculations,
    and portfolio valuation snapshots in SQLite.
    """
    def __init__(self, db: Database):
        self.db = db

    def record_trade(
        self,
        pair: str,
        side: str,
        price: float,
        amount: float,
        fee: float,
        fee_asset: str,
        is_paper: bool = True
    ):
        """
        Record an executed buy/sell trade and update position cost basis.
        """
        base_asset = pair.upper().replace("_IDR", "").replace("IDR", "")
        side = side.upper()

        with self.db.get_connection() as conn:
            # 1. Insert into transactions
            conn.execute(
                """
                INSERT INTO transactions (pair, side, order_type, price, amount, fee, fee_asset, is_paper)
                VALUES (?, ?, 'LIMIT', ?, ?, ?, ?, ?)
                """,
                (pair, side, price, amount, fee, fee_asset, 1 if is_paper else 0)
            )

            # 2. Update position
            cursor = conn.cursor()
            cursor.execute("SELECT amount, cost_basis_idr, total_invested_idr FROM positions WHERE asset = ?", (base_asset,))
            row = cursor.fetchone()

            curr_amount = row[0] if row else 0.0
            curr_cost_basis = row[1] if row else 0.0
            curr_invested = row[2] if row else 0.0

            trade_cost = (price * amount) + (fee if fee_asset.upper() == "IDR" else 0.0)

            if side == "BUY":
                new_amount = curr_amount + amount
                new_invested = curr_invested + trade_cost
                # Weighted average cost basis: (old_val + new_val) / new_amount
                new_cost_basis = new_invested / new_amount if new_amount > 0 else 0.0
            else:  # SELL
                new_amount = max(0.0, curr_amount - amount)
                # On sell, cost basis per unit remains unchanged, total invested scales down
                new_cost_basis = curr_cost_basis if new_amount > 0 else 0.0
                new_invested = new_cost_basis * new_amount

            conn.execute(
                """
                INSERT INTO positions (asset, amount, cost_basis_idr, total_invested_idr, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(asset) DO UPDATE SET
                    amount = excluded.amount,
                    cost_basis_idr = excluded.cost_basis_idr,
                    total_invested_idr = excluded.total_invested_idr,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (base_asset, new_amount, new_cost_basis, new_invested)
            )
            conn.commit()

    def process_manual_asset_disposal(
        self,
        asset: str,
        amount_disposed: float,
        estimated_market_price: float
    ) -> Dict[str, Any]:
        """
        Passively records an external/manual asset sale or withdrawal executed by Supervisor
        directly inside the Indodax app.

        KiBot V3 executes NO sell orders itself.
        This method solely:
        1. Scales down position amount & invested capital using existing cost basis (pro-rata FIFO).
        2. Estimates realized P&L based on estimated market price at the moment of delta detection.
        3. Updates SQLite positions and records the event.
        """
        asset_clean = asset.upper()
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT amount, cost_basis_idr, total_invested_idr FROM positions WHERE asset = ?",
                (asset_clean,)
            )
            row = cursor.fetchone()
            if not row or row[0] <= 0:
                return {
                    "asset": asset_clean,
                    "amount_disposed": amount_disposed,
                    "cost_basis_idr": 0.0,
                    "estimated_proceeds_idr": round(amount_disposed * estimated_market_price, 2),
                    "estimated_realized_pnl_idr": 0.0,
                    "remaining_amount": 0.0,
                }

            curr_amount = row[0]
            cost_basis = row[1]
            actual_disposed = min(curr_amount, amount_disposed)
            remaining_amount = max(0.0, curr_amount - actual_disposed)

            # Pro-rata cost basis reduction
            cost_of_disposed = actual_disposed * cost_basis
            remaining_invested = remaining_amount * cost_basis

            estimated_proceeds = actual_disposed * estimated_market_price
            estimated_realized_pnl = estimated_proceeds - cost_of_disposed

            conn.execute(
                """
                UPDATE positions SET
                    amount = ?,
                    total_invested_idr = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE asset = ?
                """,
                (remaining_amount, remaining_invested, asset_clean)
            )

            # Record into events
            event_meta = {
                "estimated_price": estimated_market_price,
                "cost_basis_idr": cost_basis,
                "estimated_proceeds_idr": round(estimated_proceeds, 2),
                "estimated_realized_pnl_idr": round(estimated_realized_pnl, 2),
                "is_manual_external": True,
            }
            conn.execute(
                """
                INSERT INTO events (event_type, asset, amount, metadata_json)
                VALUES ('manual_disposal', ?, ?, ?)
                """,
                (asset_clean, actual_disposed, json.dumps(event_meta))
            )
            conn.commit()

            return {
                "asset": asset_clean,
                "amount_disposed": actual_disposed,
                "cost_basis_idr": cost_basis,
                "estimated_price": estimated_market_price,
                "estimated_proceeds_idr": round(estimated_proceeds, 2),
                "estimated_realized_pnl_idr": round(estimated_realized_pnl, 2),
                "remaining_amount": remaining_amount,
            }

    def get_position(self, asset: str) -> Optional[Position]:
        asset_clean = asset.upper()
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT asset, amount, cost_basis_idr, total_invested_idr FROM positions WHERE asset = ?",
                (asset_clean,)
            )
            row = cursor.fetchone()
            if row:
                return Position(
                    asset=row[0],
                    amount=row[1],
                    cost_basis_idr=row[2],
                    total_invested_idr=row[3]
                )
            return None

    def get_all_positions(self) -> Dict[str, Position]:
        positions = {}
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset, amount, cost_basis_idr, total_invested_idr FROM positions WHERE amount > 0")
            for row in cursor.fetchall():
                positions[row[0]] = Position(
                    asset=row[0],
                    amount=row[1],
                    cost_basis_idr=row[2],
                    total_invested_idr=row[3]
                )
        return positions

    def take_snapshot(
        self,
        cash_idr: float,
        asset_prices: Dict[str, float],
        regime_phase: str = "NORMAL",
        is_paper: bool = True
    ) -> Dict[str, Any]:
        """
        Compute total equity, allocation weights, and persist snapshot.
        """
        positions = self.get_all_positions()
        equity = cash_idr
        asset_values = {}

        for asset, pos in positions.items():
            price = asset_prices.get(asset, 0.0)
            val = pos.amount * price
            asset_values[asset] = val
            equity += val

        allocations = {}
        if equity > 0:
            allocations["IDR"] = round(cash_idr / equity, 4)
            for asset, val in asset_values.items():
                allocations[asset] = round(val / equity, 4)

        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_snapshots (total_equity_idr, cash_idr, allocations_json, regime_phase, is_paper)
                VALUES (?, ?, ?, ?, ?)
                """,
                (equity, cash_idr, json.dumps(allocations), regime_phase, 1 if is_paper else 0)
            )
            conn.commit()

        return {
            "total_equity_idr": equity,
            "cash_idr": cash_idr,
            "allocations": allocations,
            "regime_phase": regime_phase
        }

    def deposit_cash(self, amount: float):
        """Adds IDR cash deposit and registers event."""
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO positions (asset, amount, cost_basis_idr, total_invested_idr, updated_at)
                VALUES ('IDR', ?, 1.0, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(asset) DO UPDATE SET
                    amount = amount + excluded.amount,
                    total_invested_idr = total_invested_idr + excluded.total_invested_idr,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (amount, amount)
            )
            conn.execute(
                "INSERT INTO events (event_type, asset, amount, metadata_json) VALUES ('manual_topup', 'IDR', ?, '{}')",
                (amount,)
            )
            conn.commit()

    def withdraw_cash(self, amount: float) -> bool:
        """Withdraws IDR cash if balance is sufficient."""
        pos = self.get_position("IDR")
        curr_cash = pos.amount if pos else 0.0
        if curr_cash < amount:
            return False

        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE positions SET
                    amount = amount - ?,
                    total_invested_idr = total_invested_idr - ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE asset = 'IDR'
                """,
                (amount, amount)
            )
            conn.execute(
                "INSERT INTO events (event_type, asset, amount, metadata_json) VALUES ('manual_withdraw', 'IDR', ?, '{}')",
                (amount,)
            )
            conn.commit()
        return True

    def get_holdings(self) -> Dict[str, float]:
        """Returns map of all assets and amounts."""
        holdings = {}
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset, amount FROM positions WHERE amount > 0")
            for row in cursor.fetchall():
                holdings[row[0]] = row[1]
        return holdings

    def get_total_cost_basis(self) -> float:
        """Returns total invested IDR across active positions."""
        total = 0.0
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT total_invested_idr FROM positions WHERE amount > 0")
            for row in cursor.fetchall():
                total += row[0]
        return total

    def get_nav(self, prices: Dict[str, float]) -> float:
        """Computes Net Asset Value in IDR."""
        holdings = self.get_holdings()
        nav = 0.0
        for asset, amount in holdings.items():
            if asset == "IDR":
                nav += amount
            else:
                nav += amount * prices.get(asset, 0.0)
        return nav

    def get_monthly_topup_total(self, year_month: Optional[str] = None) -> float:
        """
        Calculates total IDR spent on BUY transactions within a calendar month.
        Format of year_month: 'YYYY-MM'. Defaults to current UTC/local month.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if year_month:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(price * amount), 0.0)
                    FROM transactions
                    WHERE side = 'BUY' AND strftime('%Y-%m', timestamp) = ?
                    """,
                    (year_month,)
                )
            else:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(price * amount), 0.0)
                    FROM transactions
                    WHERE side = 'BUY' AND strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')
                    """
                )
            row = cursor.fetchone()
            return float(row[0]) if row else 0.0


