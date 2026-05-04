#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv_early() -> None:
    candidates = [
        ROOT_DIR / ".env.polymarket",
        ROOT_DIR / ".env.kibot_manager",
        ROOT_DIR / ".env.kibot",
        ROOT_DIR / ".env.server",
        ROOT_DIR / ".env",
        Path(".env.polymarket"),
        Path(".env.kibot_manager"),
        Path(".env.kibot"),
        Path(".env.server"),
        Path(".env"),
        Path("../.env"),
    ]
    explicit = os.getenv("KIBOT_POLYMARKET_ENV_FILE")
    if explicit:
        candidates.insert(0, Path(explicit))
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv_early()

try:
    from eth_account import Account
except Exception:
    Account = None

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import BalanceAllowanceParams, MarketOrderArgs, OrderArgs
except Exception:
    ClobClient = None
    BalanceAllowanceParams = None
    MarketOrderArgs = None
    OrderArgs = None


ROOT = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "polymarket_state.json"
PAPER_LEDGER_FILE = STATE_DIR / "polymarket_paper_ledger.json"

BIND_HOST = os.getenv("KIBOT_POLYMARKET_BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.getenv("KIBOT_POLYMARKET_BIND_PORT", "11600"))
REFRESH_SEC = int(os.getenv("KIBOT_POLYMARKET_REFRESH_SEC", "45"))
HTTP_TIMEOUT_SEC = float(os.getenv("KIBOT_POLYMARKET_TIMEOUT_SEC", "12"))
TOP_MARKETS = int(os.getenv("KIBOT_POLYMARKET_TOP_MARKETS", "12"))
MIN_LIQUIDITY = float(os.getenv("KIBOT_POLYMARKET_MIN_LIQUIDITY", "5000"))
MAX_SPREAD = float(os.getenv("KIBOT_POLYMARKET_MAX_SPREAD", "0.05"))
EXECUTION_ENABLED = os.getenv("KIBOT_POLYMARKET_ENABLE_LIVE_EXECUTION", "false").lower() == "true"
PAPER_TRADE_CAPITAL_USD = float(os.getenv("KIBOT_POLYMARKET_PAPER_TRADE_CAPITAL_USD", "10"))
PAPER_TRADE_MAX_ORDER_USD = float(
    os.getenv(
        "KIBOT_POLYMARKET_PAPER_TRADE_MAX_ORDER_USD",
        str(PAPER_TRADE_CAPITAL_USD if PAPER_TRADE_CAPITAL_USD > 0 else 10.0),
    )
)
AUTH_TOKEN = (
    os.getenv("KIBOT_POLYMARKET_API_TOKEN")
    or os.getenv("KIBOT_OLLAMA_GATEWAY_TOKEN")
    or os.getenv("OLLAMA_API_KEY")
    or ""
).strip()

GEOBLOCK_URL = os.getenv("KIBOT_POLYMARKET_GEOBLOCK_URL", "https://polymarket.com/api/geoblock")
GAMMA_MARKETS_URL = os.getenv("KIBOT_POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com/markets")
CLOB_HOST = os.getenv("KIBOT_POLYMARKET_CLOB_HOST", "https://clob-v2.polymarket.com")
SIMPLIFIED_MARKETS_URL = os.getenv("KIBOT_POLYMARKET_SIMPLIFIED_URL", f"{CLOB_HOST}/simplified-markets")
DATA_API_BASE_URL = os.getenv("KIBOT_POLYMARKET_DATA_API_URL", "https://data-api.polymarket.com")
POSITIONS_URL = os.getenv("KIBOT_POLYMARKET_POSITIONS_URL", f"{DATA_API_BASE_URL}/positions")
CLOSED_POSITIONS_URL = os.getenv("KIBOT_POLYMARKET_CLOSED_POSITIONS_URL", f"{DATA_API_BASE_URL}/closed-positions")
VALUE_URL = os.getenv("KIBOT_POLYMARKET_VALUE_URL", f"{DATA_API_BASE_URL}/value")
ACTIVITY_URL = os.getenv("KIBOT_POLYMARKET_ACTIVITY_URL", f"{DATA_API_BASE_URL}/activity")
ALCHEMY_RPC_URL = (
    os.getenv("ALCHEMY_URL")
    or os.getenv("POLYGON_MAINNET_RPC_URL")
    or os.getenv("POLYGON_RPC_URL")
    or ""
).strip()
PRIVATE_KEY = (
    os.getenv("KIBOT_POLYMARKET_PRIVATE_KEY")
    or os.getenv("POLYGON_KEY")
    or os.getenv("PHANTOM_WALLET_PRIVATE_KEY")
    or ""
).strip()
CHAIN_ID = int(os.getenv("KIBOT_POLYMARKET_CHAIN_ID", "137"))

_state_lock = threading.RLock()
_cached_state: Dict[str, Any] = {}


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _safe_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except Exception:
        return 0


def _ensure_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
    return []


ASSET_KEYWORDS: Dict[str, List[str]] = {
    "btc": ["btc", "bitcoin"],
    "eth": ["eth", "ethereum"],
    "sol": ["sol", "solana"],
    "xrp": ["xrp", "ripple"],
    "doge": ["doge", "dogecoin"],
    "bnb": ["bnb", "binance coin"],
    "ada": ["ada", "cardano"],
    "sui": ["sui"],
    "ltc": ["ltc", "litecoin"],
    "altseason": ["altseason", "alt season", "altcoin season"],
}

CRYPTO_CONTEXT_HINTS = (
    "bitcoin",
    "ethereum",
    "solana",
    "ripple",
    "dogecoin",
    "cardano",
    "litecoin",
    "binance",
    "crypto",
    "cryptocurrency",
    "token",
    "tokens",
    "coin",
    "coins",
    "altcoin",
    "blockchain",
    "defi",
    "etf",
    "spot etf",
    "sec",
    "wallet",
    "mainnet",
    "layer 1",
    "layer 2",
)

ASSET_REGEX: Dict[str, List[re.Pattern[str]]] = {
    asset: [
        re.compile(rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])")
        for alias in aliases
    ]
    for asset, aliases in ASSET_KEYWORDS.items()
}

BULLISH_HINTS = (
    "above",
    "reach",
    "hits",
    "hit",
    "surpass",
    "break",
    "approval",
    "approved",
    "bull",
    "rally",
    "ath",
    "up",
    "rise",
)

BEARISH_HINTS = (
    "below",
    "delay",
    "delayed",
    "ban",
    "hack",
    "exploit",
    "crash",
    "recession",
    "lawsuit",
    "depeg",
    "default",
    "fails",
    "failure",
    "selloff",
    "drops",
)


class PolymarketEngine:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "KiBot-Polymarket/1.0"})
        self._client: Optional[Any] = None
        self._client_lock = threading.RLock()
        self._paper_lock = threading.RLock()

    def _request_json(self, url: str, *, params: Optional[Dict[str, Any]] = None, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Any:
        """HTTP request with exponential backoff on 429/5xx."""
        max_retries = 3
        backoff = 1.0
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                response = self.session.request(method, url, params=params, json=body, timeout=HTTP_TIMEOUT_SEC)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < max_retries:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                response.raise_for_status()
                return response.json()
            except Exception as err:
                last_err = err
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise last_err

    def _rpc_call(self, method: str, params: List[Any]) -> Any:
        if not ALCHEMY_RPC_URL:
            return None
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        response = self.session.post(ALCHEMY_RPC_URL, json=payload, timeout=HTTP_TIMEOUT_SEC)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            return None
        return data.get("result") if isinstance(data, dict) else None

    def wallet_address(self) -> str:
        if not PRIVATE_KEY or Account is None:
            return ""
        try:
            return str(Account.from_key(PRIVATE_KEY).address)
        except Exception:
            return ""

    def _native_balance_matic(self) -> Optional[float]:
        address = self.wallet_address()
        if not address:
            return None
        raw = self._rpc_call("eth_getBalance", [address, "latest"])
        if not raw:
            return None
        try:
            return int(raw, 16) / (10 ** 18)
        except Exception:
            return None

    def _build_client(self) -> Optional[Any]:
        if not PRIVATE_KEY or ClobClient is None:
            return None
        with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                client = ClobClient(CLOB_HOST, chain_id=CHAIN_ID, key=PRIVATE_KEY)
                creds = client.create_or_derive_api_creds()
                client.set_api_creds(creds)
                self._client = client
            except Exception:
                self._client = None
            return self._client

    def _paper_trade_mode(self) -> bool:
        return os.environ.get("KIBOT_POLYMARKET_PAPER_TRADE", "true").lower() == "true"

    def _paper_trade_capital_usd(self) -> float:
        return max(0.0, float(PAPER_TRADE_CAPITAL_USD))

    def _paper_trade_max_order_usd(self) -> float:
        max_order = float(PAPER_TRADE_MAX_ORDER_USD or 0.0)
        if max_order <= 0.0:
            return self._paper_trade_capital_usd()
        return max_order

    def _load_paper_ledger(self) -> Dict[str, Any]:
        default_cash = self._paper_trade_capital_usd()
        ledger: Dict[str, Any] = {
            "starting_capital_usd": default_cash,
            "cash_usd": default_cash,
            "positions": {},
            "events": [],
            "updated_at": "",
        }
        if not PAPER_LEDGER_FILE.exists():
            return ledger
        try:
            raw = json.loads(PAPER_LEDGER_FILE.read_text(encoding="utf-8"))
        except Exception:
            return ledger
        if not isinstance(raw, dict):
            return ledger
        starting = _safe_float(raw.get("starting_capital_usd"))
        cash = _safe_float(raw.get("cash_usd"))
        if starting > 0:
            ledger["starting_capital_usd"] = starting
        if cash >= 0:
            ledger["cash_usd"] = cash
        positions: Dict[str, Any] = {}
        raw_positions = raw.get("positions") if isinstance(raw.get("positions"), dict) else {}
        for token_id, payload in raw_positions.items():
            if not isinstance(payload, dict):
                continue
            token_key = str(token_id or "").strip()
            if not token_key:
                continue
            positions[token_key] = {
                "token_qty": max(0.0, _safe_float(payload.get("token_qty"))),
                "avg_price": max(0.0, _safe_float(payload.get("avg_price"))),
                "last_price": max(0.0, _safe_float(payload.get("last_price"))),
                "condition_id": str(payload.get("condition_id") or ""),
                "slug": str(payload.get("slug") or ""),
                "title": str(payload.get("title") or ""),
                "end_date": str(payload.get("end_date") or ""),
                "outcome": str(payload.get("outcome") or ""),
                "negative_risk": bool(payload.get("negative_risk")),
            }
        ledger["positions"] = positions
        ledger["events"] = _ensure_list(raw.get("events"))
        ledger["updated_at"] = str(raw.get("updated_at") or "")
        return ledger

    def _paper_positions_from_ledger(self, ledger: Dict[str, Any], markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        positions = ledger.get("positions") if isinstance(ledger.get("positions"), dict) else {}
        market_index = self._ledger_market_index(markets)
        paper_positions: List[Dict[str, Any]] = []
        for token_id, payload in positions.items():
            if not isinstance(payload, dict):
                continue
            token_key = str(token_id or "").strip().lower()
            if not token_key:
                continue
            market = market_index.get(token_key)
            token_qty = max(0.0, _safe_float(payload.get("token_qty")))
            avg_price = max(0.0, _safe_float(payload.get("avg_price")))
            last_price = max(0.0, _safe_float(payload.get("last_price")))
            if last_price <= 0.0 and market:
                last_price = _safe_float(market.get("implied_prob_yes") or market.get("midpoint") or market.get("last_trade_price"))
            if avg_price <= 0.0:
                avg_price = last_price or 0.5
            current_price = last_price or avg_price or 0.5
            initial_value = token_qty * avg_price
            current_value = token_qty * current_price
            percent_pnl = ((current_value - initial_value) / initial_value * 100.0) if initial_value > 0 else 0.0
            paper_positions.append(
                {
                    "proxyWallet": "",
                    "asset": token_key,
                    "token_id": token_key,
                    "conditionId": str(payload.get("condition_id") or (market or {}).get("condition_id") or ""),
                    "size": round(token_qty, 8),
                    "avgPrice": round(avg_price, 6),
                    "initialValue": round(initial_value, 4),
                    "currentValue": round(current_value, 4),
                    "cashPnl": round(current_value - initial_value, 4),
                    "percentPnl": round(percent_pnl, 4),
                    "totalBought": round(initial_value, 4),
                    "realizedPnl": 0.0,
                    "percentRealizedPnl": 0.0,
                    "curPrice": round(current_price, 6),
                    "redeemable": False,
                    "mergeable": False,
                    "title": str(payload.get("title") or (market or {}).get("question") or ""),
                    "slug": str(payload.get("slug") or (market or {}).get("slug") or ""),
                    "icon": "",
                    "eventSlug": str((market or {}).get("slug") or ""),
                    "outcome": str(payload.get("outcome") or (market or {}).get("yes_outcome") or ""),
                    "outcomeIndex": 0,
                    "oppositeOutcome": "",
                    "oppositeAsset": "",
                    "endDate": str(payload.get("end_date") or (market or {}).get("end_date") or ""),
                    "negativeRisk": bool(payload.get("negative_risk") or (market or {}).get("negativeRisk")),
                    "paper_trade": True,
                }
            )
        return sorted(paper_positions, key=lambda item: abs(_safe_float(item.get("percentPnl"))), reverse=True)

    def _save_paper_ledger(self, ledger: Dict[str, Any]) -> None:
        payload = {
            "starting_capital_usd": max(0.0, _safe_float(ledger.get("starting_capital_usd"))),
            "cash_usd": max(0.0, _safe_float(ledger.get("cash_usd"))),
            "positions": ledger.get("positions") if isinstance(ledger.get("positions"), dict) else {},
            "events": ledger.get("events") if isinstance(ledger.get("events"), list) else [],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _atomic_write(PAPER_LEDGER_FILE, payload)

    def _ledger_market_index(self, markets: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}
        for market in markets:
            if not isinstance(market, dict):
                continue
            for key in (
                market.get("condition_id"),
                market.get("slug"),
                market.get("yes_token_id"),
                market.get("no_token_id"),
            ):
                token_key = str(key or "").strip().lower()
                if token_key:
                    index[token_key] = market
        return index

    def _position_hours_remaining(self, position: Dict[str, Any]) -> Optional[float]:
        end_date_str = str(position.get("end_date") or position.get("endDate") or "")
        if not end_date_str:
            return None
        try:
            from datetime import datetime, timezone

            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
                try:
                    end_dt = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    return max(0.0, (end_dt - now).total_seconds() / 3600.0)
                except ValueError:
                    continue
        except Exception:
            return None
        return None

    def _position_signal_score(self, position: Dict[str, Any], market: Optional[Dict[str, Any]] = None) -> float:
        if isinstance(market, dict):
            score = _safe_float(market.get("score") or market.get("alpha_score") or market.get("maker_score"))
            if score > 0:
                return max(0.0, min(1.0, score))
        percent_pnl = _safe_float(position.get("percent_pnl") or position.get("percentPnl"))
        if percent_pnl:
            return max(0.0, min(1.0, 0.5 + (percent_pnl / 100.0)))
        current_price = _safe_float(position.get("current_price") or position.get("curPrice"))
        avg_price = _safe_float(position.get("avg_price") or position.get("avgPrice"))
        if current_price > 0 and avg_price > 0:
            pnl_pct = (current_price - avg_price) / avg_price
            return max(0.0, min(1.0, 0.5 + pnl_pct))
        return 0.5

    def _build_open_position_insights(self, positions: List[Dict[str, Any]], markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        market_index = self._ledger_market_index(markets)
        insights: List[Dict[str, Any]] = []
        for raw in positions:
            if not isinstance(raw, dict):
                continue
            token_id = str(raw.get("asset") or raw.get("token_id") or raw.get("yes_token_id") or raw.get("no_token_id") or "").strip().lower()
            if not token_id:
                continue
            market = market_index.get(token_id)
            current_price = _safe_float(raw.get("curPrice") or raw.get("current_price") or (market or {}).get("implied_prob_yes"))
            avg_price = _safe_float(raw.get("avgPrice") or raw.get("avg_price"))
            size = _safe_float(raw.get("size") or raw.get("token_qty"))
            if size <= 0 and current_price > 0:
                current_value = _safe_float(raw.get("currentValue") or raw.get("current_value"))
                if current_value > 0:
                    size = current_value / max(current_price, 1e-9)
            if avg_price <= 0:
                avg_price = _safe_float(raw.get("initialValue") or raw.get("avgPrice"))
            hours_remaining = self._position_hours_remaining(raw)
            signal_score = self._position_signal_score(raw, market)
            exit_plan = self.evaluate_exit_plan(
                current_price=current_price,
                avg_entry_price=avg_price,
                hours_remaining=float(hours_remaining if hours_remaining is not None else 24.0),
                current_signal_score=signal_score,
            )
            current_value = _safe_float(raw.get("currentValue") or raw.get("current_value"))
            initial_value = _safe_float(raw.get("initialValue") or raw.get("initial_value"))
            if current_value <= 0 and current_price > 0 and size > 0:
                current_value = size * current_price
            if initial_value <= 0 and avg_price > 0 and size > 0:
                initial_value = size * avg_price
            if not current_value and current_price > 0 and size > 0:
                current_value = size * current_price
            insights.append(
                {
                    "token_id": token_id,
                    "condition_id": str(raw.get("conditionId") or raw.get("condition_id") or (market or {}).get("condition_id") or ""),
                    "slug": str(raw.get("slug") or (market or {}).get("slug") or ""),
                    "title": str(raw.get("title") or (market or {}).get("question") or ""),
                    "outcome": str(raw.get("outcome") or raw.get("side") or ""),
                    "end_date": str(raw.get("endDate") or raw.get("end_date") or (market or {}).get("end_date") or ""),
                    "size": round(size, 8),
                    "avg_price": round(avg_price, 6),
                    "current_price": round(current_price, 6),
                    "initial_value": round(initial_value, 4),
                    "current_value": round(current_value, 4),
                    "cash_pnl": round(_safe_float(raw.get("cashPnl") or raw.get("cash_pnl") or (current_value - initial_value)), 4),
                    "percent_pnl": round(_safe_float(raw.get("percentPnl") or raw.get("percent_pnl") or ((current_value - initial_value) / initial_value * 100.0 if initial_value > 0 else 0.0)), 4),
                    "percent_realized_pnl": round(_safe_float(raw.get("percentRealizedPnl") or raw.get("percent_realized_pnl")), 4),
                    "signal_score": round(signal_score, 4),
                    "hours_remaining": round(float(hours_remaining), 2) if hours_remaining is not None else None,
                    "paper_trade": self._paper_trade_mode(),
                    "negative_risk": bool(raw.get("negativeRisk") or raw.get("negative_risk") or (market or {}).get("neg_risk")),
                    "exit_plan": exit_plan,
                    "market_score": round(_safe_float((market or {}).get("score")), 4) if market else None,
                    "maker_score": round(_safe_float((market or {}).get("maker_score")), 4) if market else None,
                    "deadline_proximity": (market or {}).get("deadline_proximity") if isinstance((market or {}).get("deadline_proximity"), dict) else {},
                }
            )
        action_order = {"STOP_LOSS": 0, "TIME_CUT": 1, "TAKE_PROFIT": 2, "HOLD": 3}
        return sorted(
            insights,
            key=lambda item: (
                action_order.get(str((item.get("exit_plan") or {}).get("action") or "HOLD"), 4),
                -abs(_safe_float(item.get("percent_pnl"))),
                str(item.get("title") or ""),
            ),
        )

    def _balance_allowance(self) -> Dict[str, Any]:
        client = self._build_client()
        if client is None or BalanceAllowanceParams is None:
            return {}
        try:
            payload = client.get_balance_allowance(BalanceAllowanceParams(asset_type="COLLATERAL"))
            return payload if isinstance(payload, dict) else {"raw": payload}
        except Exception as error:
            return {"error": str(error)}

    def _geoblock(self) -> Dict[str, Any]:
        try:
            payload = self._request_json(GEOBLOCK_URL)
            return payload if isinstance(payload, dict) else {}
        except Exception as error:
            return {"blocked": None, "error": str(error)}

    def _fetch_markets(self) -> List[Dict[str, Any]]:
        try:
            payload = self._request_json(
                GAMMA_MARKETS_URL,
                params={"active": "true", "closed": "false", "limit": "200"},
            )
            return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
        except Exception:
            return []

    def _fetch_simplified_markets(self) -> List[Dict[str, Any]]:
        try:
            payload = self._request_json(SIMPLIFIED_MARKETS_URL)
            if isinstance(payload, dict):
                data = payload.get("data")
                return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
            return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
        except Exception:
            return []

    def _fetch_data_snapshot(self, url: str, *, address: str) -> Any:
        if not address:
            return {}
        try:
            return self._request_json(url, params={"user": address})
        except Exception:
            return {}

    def _market_score(self, market: Dict[str, Any]) -> float:
        liquidity = _safe_float(market.get("liquidity"))
        volume_24h = _safe_float(market.get("volume24hr"))
        spread = _safe_float(market.get("spread"))
        liquidity_score = min(liquidity / 150_000.0, 1.0)
        volume_score = min(volume_24h / 125_000.0, 1.0)
        spread_score = max(0.0, 1.0 - min(spread / max(MAX_SPREAD, 0.005), 1.0))
        reward_score = min(_safe_float(market.get("reward_daily_rate")) / 10.0, 1.0)
        momentum_score = min(abs(_safe_float(market.get("one_day_price_change"))) / 0.20, 1.0)
        return round(
            (liquidity_score * 0.32)
            + (volume_score * 0.28)
            + (spread_score * 0.20)
            + (reward_score * 0.10)
            + (momentum_score * 0.10),
            4,
        )

    def _maker_score(self, market: Dict[str, Any]) -> float:
        spread = _safe_float(market.get("spread"))
        reward_daily_rate = _safe_float(market.get("reward_daily_rate"))
        fees_enabled = bool(market.get("fees_enabled"))
        reward_spread_ok = spread <= max(_safe_float(market.get("reward_max_spread")) / 100.0, MAX_SPREAD)
        liquidity = _safe_float(market.get("liquidity"))
        volume_24h = _safe_float(market.get("volume24hr"))
        return round(
            (0.35 if fees_enabled else 0.0)
            + (0.20 if reward_daily_rate > 0 else 0.0)
            + (0.15 if reward_spread_ok else 0.0)
            + min(liquidity / 200_000.0, 0.20)
            + min(volume_24h / 200_000.0, 0.10),
            4,
        )

    def _asset_signal(self, market: Dict[str, Any]) -> Dict[str, Any]:
        question = str(market.get("question") or "").lower()
        description = str(market.get("description") or "").lower()
        category = str(market.get("category") or "").lower()
        tags = " ".join(str(item).lower() for item in _ensure_list(market.get("tags")))
        event_titles = " ".join(str(item.get("title") or "").lower() for item in _ensure_list(market.get("events")) if isinstance(item, dict))
        event_descriptions = " ".join(
            str(item.get("description") or "").lower() for item in _ensure_list(market.get("events")) if isinstance(item, dict)
        )
        context_blob = " ".join(part for part in [question, description, category, tags, event_titles, event_descriptions] if part)
        has_crypto_context = any(token in context_blob for token in CRYPTO_CONTEXT_HINTS)
        matched_asset = ""
        for asset, aliases in ASSET_KEYWORDS.items():
            patterns = ASSET_REGEX.get(asset) or []
            if any(pattern.search(question) for pattern in patterns):
                matched_asset = asset
                break
        if not matched_asset:
            return {}
        strong_alias_present = any(
            len(alias) > 3 and alias in context_blob
            for alias in ASSET_KEYWORDS.get(matched_asset, [])
        )
        price_context = any(token in question for token in ("$", "price", "priced", "market cap", "etf", "all-time high"))
        if not (has_crypto_context or strong_alias_present or price_context):
            return {}

        yes_prob = _safe_float(market.get("implied_prob_yes"))
        conviction = min(abs(yes_prob - 0.5) * 2.0, 1.0)
        bullish = any(token in question for token in BULLISH_HINTS)
        bearish = any(token in question for token in BEARISH_HINTS)
        direction = ""
        if bullish and yes_prob >= 0.55:
            direction = "LONG"
        elif bullish and yes_prob <= 0.45:
            direction = "SHORT"
        elif bearish and yes_prob >= 0.55:
            direction = "SHORT"
        elif bearish and yes_prob <= 0.45:
            direction = "LONG"
        if not direction:
            return {}

        score = round(
            min(
                1.0,
                (conviction * 0.55)
                + min(_safe_float(market.get("liquidity")) / 250_000.0, 0.20)
                + min(_safe_float(market.get("volume24hr")) / 250_000.0, 0.20)
                + min(abs(_safe_float(market.get("one_day_price_change"))) / 0.10, 0.05),
            ),
            4,
        )
        return {
            "asset": matched_asset,
            "direction": direction,
            "score": score,
            "question": str(market.get("question") or ""),
            "mapped_pair": "" if matched_asset == "altseason" else f"{matched_asset}_idr",
        }

    def _normalize_market(self, market: Dict[str, Any]) -> Dict[str, Any]:
        token_ids = _ensure_list(market.get("clobTokenIds"))
        outcomes = _ensure_list(market.get("outcomes"))
        best_ask = _safe_float(market.get("bestAsk"))
        best_bid = _safe_float(market.get("bestBid"))
        spread = _safe_float(market.get("spread"))
        if spread <= 0 and best_ask > 0 and best_bid > 0:
            spread = max(best_ask - best_bid, 0.0)
        outcome_prices = _ensure_list(market.get("outcomePrices"))
        outcome_price_yes = _safe_float(outcome_prices[0] if outcome_prices else 0.0)
        midpoint = 0.0
        if best_bid > 0 and best_ask > 0:
            midpoint = (best_bid + best_ask) / 2.0
        elif outcome_price_yes > 0:
            midpoint = outcome_price_yes
        reward_daily_rate = sum(_safe_float(item.get("rewardsDailyRate")) for item in _ensure_list(market.get("clobRewards")))
        reward_min_size = _safe_float(market.get("rewardsMinSize"))
        reward_max_spread = _safe_float(market.get("rewardsMaxSpread"))
        normalized = {
            "question": str(market.get("question") or ""),
            "slug": str(market.get("slug") or market.get("questionID") or ""),
            "category": str(market.get("category") or ""),
            "description": str(market.get("description") or ""),
            "tags": _ensure_list(market.get("tags")),
            "events": _ensure_list(market.get("events")),
            "condition_id": str(market.get("conditionId") or ""),
            "yes_token_id": str(token_ids[0]) if len(token_ids) >= 1 else "",
            "no_token_id": str(token_ids[1]) if len(token_ids) >= 2 else "",
            "yes_outcome": str(outcomes[0]) if len(outcomes) >= 1 else "YES",
            "no_outcome": str(outcomes[1]) if len(outcomes) >= 2 else "NO",
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "liquidity": _safe_float(market.get("liquidityClob") or market.get("liquidity")),
            "volume24hr": _safe_float(market.get("volume24hr") or market.get("volume24h")),
            "volume1wk": _safe_float(market.get("volume1wk") or market.get("volume1wkClob")),
            "volume1mo": _safe_float(market.get("volume1mo") or market.get("volume1moClob")),
            "one_day_price_change": _safe_float(market.get("oneDayPriceChange")),
            "one_week_price_change": _safe_float(market.get("oneWeekPriceChange")),
            "one_month_price_change": _safe_float(market.get("oneMonthPriceChange")),
            "fees_enabled": bool(market.get("feesEnabled")),
            "order_min_size": _safe_float(market.get("orderMinSize")),
            "min_tick": _safe_float(market.get("orderPriceMinTickSize")),
            "midpoint": round(midpoint, 4),
            "implied_prob_yes": round(midpoint, 4),
            "last_trade_price": _safe_float(market.get("lastTradePrice")),
            "reward_daily_rate": reward_daily_rate,
            "reward_min_size": reward_min_size,
            "reward_max_spread": reward_max_spread,
            "end_date": str(market.get("endDate") or ""),
            "accepting_orders": bool(market.get("acceptingOrders")),
            "active": bool(market.get("active")),
            "closed": bool(market.get("closed")),
        }
        normalized["score"] = self._market_score(normalized)
        normalized["maker_score"] = self._maker_score(normalized)
        normalized["asset_signal"] = self._asset_signal(normalized)
        normalized["alpha_score"] = round(
            normalized["score"] * 0.60 + _safe_float((normalized["asset_signal"] or {}).get("score")) * 0.40,
            4,
        )
        normalized["execution_style"] = (
            "MAKER_REBATE"
            if normalized["maker_score"] >= 0.55 and normalized["fees_enabled"]
            else ("PASSIVE_REWARD" if normalized["maker_score"] >= 0.45 else "OBSERVE")
        )
        # Deadline proximity scoring (v7.3)
        normalized["deadline_proximity"] = self._deadline_proximity(normalized)
        return normalized

    def _deadline_proximity(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Score markets by how close they are to resolution with high certainty."""
        end_date_str = str(market.get("end_date") or "")
        if not end_date_str:
            return {"hours_left": None, "near_certain": False, "time_decay_score": 0.0}
        try:
            from datetime import datetime, timezone
            # Parse various date formats
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
                try:
                    end_dt = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                return {"hours_left": None, "near_certain": False, "time_decay_score": 0.0}

            now = datetime.now(timezone.utc)
            hours_left = max(0, (end_dt - now).total_seconds() / 3600)
            prob = _safe_float(market.get("implied_prob_yes"))
            certainty = max(prob, 1.0 - prob)  # distance from 50%
            near_certain = certainty >= 0.90 and hours_left <= 48

            # Time decay score: higher = more attractive for theta capture
            time_factor = max(0, 1.0 - (hours_left / 168))  # peaks at 0h, zero at 7d
            certainty_factor = max(0, (certainty - 0.5) * 2)  # 0 at 50%, 1 at 100%
            time_decay_score = round(time_factor * 0.6 + certainty_factor * 0.4, 4)

            return {
                "hours_left": round(hours_left, 1),
                "near_certain": near_certain,
                "certainty": round(certainty, 4),
                "time_decay_score": time_decay_score,
            }
        except Exception:
            return {"hours_left": None, "near_certain": False, "time_decay_score": 0.0}

    def _normalized_markets(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for market in markets:
            if not market.get("active") or market.get("closed") or not market.get("acceptingOrders"):
                continue
            liquidity = _safe_float(market.get("liquidityClob") or market.get("liquidity"))
            if liquidity < MIN_LIQUIDITY:
                continue
            spread = _safe_float(market.get("spread"))
            best_ask = _safe_float(market.get("bestAsk"))
            best_bid = _safe_float(market.get("bestBid"))
            if spread <= 0 and best_ask > 0 and best_bid > 0:
                spread = max(best_ask - best_bid, 0.0)
            if spread > MAX_SPREAD:
                continue
            normalized.append(self._normalize_market(market))
        return normalized

    def _top_opportunities(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(markets, key=lambda item: item.get("score") or 0.0, reverse=True)[:TOP_MARKETS]

    def _maker_candidates(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates = [
            {
                "question": item.get("question"),
                "slug": item.get("slug"),
                "condition_id": item.get("condition_id"),
                "maker_score": item.get("maker_score"),
                "reward_daily_rate": item.get("reward_daily_rate"),
                "fees_enabled": item.get("fees_enabled"),
                "spread": item.get("spread"),
                "liquidity": item.get("liquidity"),
                "execution_style": item.get("execution_style"),
            }
            for item in markets
            if item.get("maker_score", 0.0) >= 0.35
        ]
        return sorted(candidates, key=lambda item: item.get("maker_score") or 0.0, reverse=True)[:TOP_MARKETS]

    def _alpha_candidates(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for item in markets:
            signal = item.get("asset_signal") if isinstance(item.get("asset_signal"), dict) else {}
            if not signal:
                continue
            candidates.append(
                {
                    "question": item.get("question"),
                    "slug": item.get("slug"),
                    "condition_id": item.get("condition_id"),
                    "asset": signal.get("asset"),
                    "mapped_pair": signal.get("mapped_pair"),
                    "direction": signal.get("direction"),
                    "signal_score": signal.get("score"),
                    "alpha_score": item.get("alpha_score"),
                    "implied_prob_yes": item.get("implied_prob_yes"),
                    "spread": item.get("spread"),
                    "liquidity": item.get("liquidity"),
                    "volume24hr": item.get("volume24hr"),
                }
            )
        return sorted(candidates, key=lambda item: item.get("alpha_score") or 0.0, reverse=True)[:TOP_MARKETS]

    def _cross_market_bias(self, markets: List[Dict[str, Any]]) -> Dict[str, Any]:
        aggregate: Dict[str, Dict[str, Any]] = {}
        for item in markets:
            signal = item.get("asset_signal") if isinstance(item.get("asset_signal"), dict) else {}
            asset = str(signal.get("asset") or "")
            direction = str(signal.get("direction") or "")
            score = _safe_float(signal.get("score"))
            if not asset or not direction or score <= 0:
                continue
            weight = score if direction == "LONG" else -score
            entry = aggregate.setdefault(
                asset,
                {
                    "net_score": 0.0,
                    "count": 0,
                    "top_questions": [],
                    "mapped_pairs": [],
                },
            )
            entry["net_score"] += weight
            entry["count"] += 1
            entry["top_questions"].append(str(item.get("question") or ""))
            mapped_pair = str(signal.get("mapped_pair") or "")
            if mapped_pair and mapped_pair not in entry["mapped_pairs"]:
                entry["mapped_pairs"].append(mapped_pair)
        out: Dict[str, Any] = {}
        for asset, entry in aggregate.items():
            net_score = float(entry.get("net_score") or 0.0)
            out[asset] = {
                "direction": "LONG" if net_score >= 0 else "SHORT",
                "score": round(min(abs(net_score), 1.0), 4),
                "count": int(entry.get("count") or 0),
                "top_questions": list(entry.get("top_questions") or [])[:3],
                "mapped_pairs": list(entry.get("mapped_pairs") or [])[:3],
            }
        return out

    def _time_decay_candidates(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find near-resolution markets with high certainty for time decay trading."""
        candidates = []
        for item in markets:
            dp = item.get("deadline_proximity") if isinstance(item.get("deadline_proximity"), dict) else {}
            if not dp.get("near_certain"):
                continue
            candidates.append({
                "question": str(item.get("question") or "")[:120],
                "slug": item.get("slug"),
                "hours_left": dp.get("hours_left"),
                "certainty": dp.get("certainty"),
                "time_decay_score": dp.get("time_decay_score"),
                "implied_prob_yes": item.get("implied_prob_yes"),
                "liquidity": item.get("liquidity"),
                "spread": item.get("spread"),
            })
        return sorted(candidates, key=lambda x: x.get("time_decay_score") or 0, reverse=True)[:6]

    def _wallet_summary(self, address: str) -> Dict[str, Any]:
        positions = self._fetch_data_snapshot(POSITIONS_URL, address=address)
        closed_positions = self._fetch_data_snapshot(CLOSED_POSITIONS_URL, address=address)
        value = self._fetch_data_snapshot(VALUE_URL, address=address)
        activity = self._fetch_data_snapshot(ACTIVITY_URL, address=address)
        position_rows = positions if isinstance(positions, list) else []
        closed_rows = closed_positions if isinstance(closed_positions, list) else []
        activity_rows = activity if isinstance(activity, list) else []
        value_rows = value if isinstance(value, list) else ([value] if isinstance(value, dict) else [])
        value_payload = value_rows[0] if value_rows and isinstance(value_rows[0], dict) else {}
        return {
            "open_positions": len(position_rows),
            "closed_positions": len(closed_rows),
            "recent_activity": len(activity_rows),
            "position_value": value_payload,
            "position_value_usd": _safe_float(value_payload.get("value")),
            "positions": position_rows,
            "top_positions": position_rows[:5],
        }

    def _ops_alerts(self, *, geoblock: Dict[str, Any], wallet_summary: Dict[str, Any], native_balance: Optional[float], cross_market_bias: Dict[str, Any], paper_trade_mode: bool) -> List[str]:
        alerts: List[str] = []
        if bool(geoblock.get("blocked")):
            alerts.append("polymarket geoblock active")
        if EXECUTION_ENABLED and not paper_trade_mode and (native_balance or 0.0) < 0.02:
            alerts.append("polygon gas balance is low")
        if EXECUTION_ENABLED and int(wallet_summary.get("open_positions") or 0) >= 8:
            alerts.append("open polymarket positions already dense")
        if not cross_market_bias:
            alerts.append("no strong cross-market bias detected")
        return alerts[:4]

    def refresh_state(self) -> Dict[str, Any]:
        geoblock = self._geoblock()
        gamma_markets = self._fetch_markets()
        simplified_markets = self._fetch_simplified_markets()
        wallet_address = self.wallet_address()
        native_balance = self._native_balance_matic()
        balance_allowance = self._balance_allowance()
        normalized_markets = self._normalized_markets(gamma_markets)
        paper_trade_mode = self._paper_trade_mode()
        paper_ledger = self._load_paper_ledger() if paper_trade_mode else {}
        top_opportunities = self._top_opportunities(normalized_markets)
        maker_candidates = self._maker_candidates(normalized_markets)
        alpha_candidates = self._alpha_candidates(normalized_markets)
        cross_market_bias = self._cross_market_bias(normalized_markets)
        time_decay = self._time_decay_candidates(normalized_markets)
        if paper_trade_mode:
            paper_positions = self._paper_positions_from_ledger(paper_ledger, normalized_markets)
            wallet_summary = {
                "open_positions": len(paper_positions),
                "closed_positions": 0,
                "recent_activity": len(paper_ledger.get("events") or []) if isinstance(paper_ledger, dict) else 0,
                "position_value": {"value": sum(_safe_float(item.get("current_value")) for item in paper_positions)},
                "position_value_usd": sum(_safe_float(item.get("current_value")) for item in paper_positions),
                "positions": paper_positions,
                "top_positions": paper_positions[:5],
                "paper_trade_mode": True,
                "paper_trade_cash_usd": _safe_float(paper_ledger.get("cash_usd")) if isinstance(paper_ledger, dict) else self._paper_trade_capital_usd(),
                "paper_trade_starting_capital_usd": _safe_float(paper_ledger.get("starting_capital_usd")) if isinstance(paper_ledger, dict) else self._paper_trade_capital_usd(),
            }
        else:
            wallet_summary = self._wallet_summary(wallet_address)
        open_position_insights = self._build_open_position_insights(wallet_summary.get("positions") if isinstance(wallet_summary.get("positions"), list) else [], normalized_markets)
        ops_alerts = self._ops_alerts(
            geoblock=geoblock,
            wallet_summary=wallet_summary,
            native_balance=native_balance,
            cross_market_bias=cross_market_bias,
            paper_trade_mode=paper_trade_mode,
        )
        state = {
            "ok": True,
            "service": "kibot-polymarket",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ready": (paper_trade_mode or bool(wallet_address)) and not bool(geoblock.get("blocked")),
            "analysis_ready": bool(normalized_markets),
            "execution_enabled": EXECUTION_ENABLED,
            "sdk_ready": bool(self._build_client()),
            "wallet_address": wallet_address,
            "native_balance_matic": native_balance,
            "wallet_summary": wallet_summary,
            "paper_trade_mode": paper_trade_mode,
            "paper_trade_capital_usd": self._paper_trade_capital_usd() if paper_trade_mode else 0.0,
            "paper_trade_max_order_usd": self._paper_trade_max_order_usd() if paper_trade_mode else 0.0,
            "paper_trade_cash_usd": _safe_float(paper_ledger.get("cash_usd")) if isinstance(paper_ledger, dict) else 0.0,
            "paper_trade_positions_count": len(paper_ledger.get("positions") or {}) if isinstance(paper_ledger, dict) else 0,
            "geoblock": geoblock,
            "gamma_market_count": len(gamma_markets),
            "simplified_market_count": len(simplified_markets),
            "top_opportunities": top_opportunities,
            "maker_candidates": maker_candidates,
            "alpha_candidates": alpha_candidates,
            "open_position_insights": open_position_insights,
            "cross_market_bias": cross_market_bias,
            "time_decay_candidates": time_decay,
            "top_markets": [str(item.get("question") or "") for item in top_opportunities[:6]],
            "ops_alerts": ops_alerts,
            "balance_allowance": balance_allowance,
            "clob_host": CLOB_HOST,
        }
        # Record probability history & detect shifts
        PROB_TRACKER.record(normalized_markets)
        prob_shift_threshold = float(os.getenv("KIBOT_POLYMARKET_PROB_SHIFT_THRESHOLD", "0.10"))
        shift_signals = PROB_TRACKER.detect_signals(normalized_markets, threshold=prob_shift_threshold)
        state["probability_shift_signals"] = shift_signals
        with _state_lock:
            _cached_state.clear()
            _cached_state.update(state)
        _atomic_write(STATE_FILE, state)
        return state

    def place_market_order(self, token_id: str, side: str, amount: float, price: float = 0.0, order_type: str = "FAK") -> Dict[str, Any]:
        paper_trade = os.environ.get("KIBOT_POLYMARKET_PAPER_TRADE", "true").lower() == "true"
        if not EXECUTION_ENABLED and not paper_trade:
            raise RuntimeError("polymarket execution disabled and paper trading is off")
            
        if paper_trade:
            return self._paper_execute_order(token_id=token_id, side=side, amount=amount, price=price, order_type=order_type, market_order=True)
            
        client = self._build_client()
        if client is None or MarketOrderArgs is None:
            raise RuntimeError("polymarket sdk unavailable")
        payload = MarketOrderArgs(
            token_id=str(token_id),
            amount=float(amount),
            side=str(side).upper(),
            price=float(price or 0.0),
            order_type=str(order_type).upper(),
        )
        order = client.create_market_order(payload)
        result = client.post_order(order, str(order_type).upper())
        return result if isinstance(result, dict) else {"raw": result}

    def place_limit_order(self, token_id: str, side: str, amount: float, price: float) -> Dict[str, Any]:
        """Place limit order to earn maker rebates (Strategy B)."""
        paper_trade = os.environ.get("KIBOT_POLYMARKET_PAPER_TRADE", "true").lower() == "true"
        if not EXECUTION_ENABLED and not paper_trade:
            raise RuntimeError("polymarket execution disabled and paper trading is off")
            
        if paper_trade:
            return self._paper_execute_order(token_id=token_id, side=side, amount=amount, price=price, order_type="GTC", market_order=False)
            
        client = self._build_client()
        if client is None or OrderArgs is None:
            raise RuntimeError("polymarket sdk unavailable")
        payload = OrderArgs(
            token_id=str(token_id),
            amount=float(amount),
            side=str(side).upper(),
            price=float(price),
        )
        order = client.create_order(payload)
        result = client.post_order(order)
        return result if isinstance(result, dict) else {"raw": result}

    def exit_position(self, token_id: str, amount: float, current_price: float) -> Dict[str, Any]:
        """Liquidate an open position to secure profits or cut losses."""
        # This is a specialized wrapper around selling.
        return self.place_market_order(
            token_id=token_id,
            side="SELL",
            amount=amount,
            price=current_price
        )

    def _paper_execute_order(self, *, token_id: str, side: str, amount: float, price: float, order_type: str, market_order: bool) -> Dict[str, Any]:
        side = str(side or "").upper()
        token_key = str(token_id or "").strip().lower()
        order_kind = "MARKET" if market_order else "LIMIT"
        with self._paper_lock:
            ledger = self._load_paper_ledger()
            positions = ledger.get("positions") if isinstance(ledger.get("positions"), dict) else {}
            before_cash = max(0.0, _safe_float(ledger.get("cash_usd")))
            starting_cash = max(0.0, _safe_float(ledger.get("starting_capital_usd")))
            if starting_cash <= 0.0:
                starting_cash = self._paper_trade_capital_usd()
            fill_price = max(0.0, float(price or 0.0))
            if fill_price <= 0.0:
                fill_price = 0.5
            executed_amount = max(0.0, float(amount or 0.0))
            if side == "BUY":
                if market_order:
                    requested_cash = executed_amount
                else:
                    requested_cash = executed_amount * fill_price
                cash_cap = min(before_cash if before_cash > 0 else starting_cash, self._paper_trade_max_order_usd())
                spent_cash = min(requested_cash, cash_cap)
                if spent_cash <= 0.0:
                    return {
                        "success": False,
                        "simulated": True,
                        "paper": True,
                        "reason": "paper_cash_exhausted",
                        "orderID": f"paper_{int(time.time() * 1000)}",
                        "order_type": order_kind,
                    }
                token_qty = spent_cash / max(fill_price, 1e-9)
                pos = positions.get(token_key, {
                    "token_qty": 0.0,
                    "avg_price": 0.0,
                    "last_price": fill_price,
                    "condition_id": "",
                    "slug": "",
                    "title": "",
                    "end_date": "",
                    "outcome": "",
                    "negative_risk": False,
                })
                prev_qty = max(0.0, _safe_float(pos.get("token_qty")))
                prev_avg = max(0.0, _safe_float(pos.get("avg_price")))
                new_qty = prev_qty + token_qty
                new_avg = ((prev_qty * prev_avg) + (token_qty * fill_price)) / new_qty if new_qty > 0 else fill_price
                pos["token_qty"] = round(new_qty, 8)
                pos["avg_price"] = round(new_avg, 6)
                pos["last_price"] = round(fill_price, 6)
                positions[token_key] = pos
                events = ledger.get("events") if isinstance(ledger.get("events"), list) else []
                events.append(
                    {
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "token_id": token_key,
                        "side": side,
                        "order_type": order_kind,
                        "filled_cash_usd": round(spent_cash, 6),
                        "filled_token_qty": round(token_qty, 8),
                        "price": round(fill_price, 6),
                        "paper": True,
                    }
                )
                ledger["events"] = events[-200:]
                ledger["cash_usd"] = round(max(0.0, before_cash - spent_cash), 6)
                ledger["positions"] = positions
                self._save_paper_ledger(ledger)
                return {
                    "success": True,
                    "simulated": True,
                    "paper": True,
                    "order_type": order_kind,
                    "side": side,
                    "token_id": token_key,
                    "filled_cash_usd": round(spent_cash, 6),
                    "filled_token_qty": round(token_qty, 8),
                    "paper_cash_usd_before": round(before_cash, 6),
                    "paper_cash_usd_after": round(ledger["cash_usd"], 6),
                    "paper_position_qty": round(new_qty, 8),
                    "transactionHash": "0xpaper" + "0" * 30,
                    "orderID": f"paper_{int(time.time() * 1000)}",
                }
            sell_qty = executed_amount
            pos = positions.get(token_key)
            held_qty = max(0.0, _safe_float(pos.get("token_qty")) if isinstance(pos, dict) else 0.0)
            sell_qty = min(sell_qty, held_qty) if held_qty > 0 else sell_qty
            if sell_qty <= 0.0:
                return {
                    "success": False,
                    "simulated": True,
                    "paper": True,
                    "reason": "paper_position_missing",
                    "orderID": f"paper_{int(time.time() * 1000)}",
                    "order_type": order_kind,
                }
            proceeds = sell_qty * fill_price
            if isinstance(pos, dict):
                remaining = max(0.0, held_qty - sell_qty)
                if remaining <= 0.0:
                    positions.pop(token_key, None)
                else:
                    pos["token_qty"] = round(remaining, 8)
                    pos["last_price"] = round(fill_price, 6)
                    positions[token_key] = pos
            events = ledger.get("events") if isinstance(ledger.get("events"), list) else []
            events.append(
                {
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "token_id": token_key,
                    "side": side,
                    "order_type": order_kind,
                    "filled_cash_usd": round(proceeds, 6),
                    "filled_token_qty": round(sell_qty, 8),
                    "price": round(fill_price, 6),
                    "paper": True,
                }
            )
            ledger["events"] = events[-200:]
            ledger["cash_usd"] = round(max(0.0, before_cash + proceeds), 6)
            ledger["positions"] = positions
            self._save_paper_ledger(ledger)
            return {
                "success": True,
                "simulated": True,
                "paper": True,
                "order_type": order_kind,
                "side": side,
                "token_id": token_key,
                "filled_cash_usd": round(proceeds, 6),
                "filled_token_qty": round(sell_qty, 8),
                "paper_cash_usd_before": round(before_cash, 6),
                "paper_cash_usd_after": round(ledger["cash_usd"], 6),
                "paper_position_qty": round(max(0.0, _safe_float(positions.get(token_key, {}).get("token_qty")) if token_key in positions else 0.0), 8),
                "transactionHash": "0xpaper" + "0" * 30,
                "orderID": f"paper_{int(time.time() * 1000)}",
            }

    def evaluate_exit_plan(
        self,
        current_price: float,
        avg_entry_price: float,
        hours_remaining: float,
        current_signal_score: float
    ) -> Dict[str, Any]:
        """
        Evaluate whether an open position should be exited (Take Profit or Stop Loss).
        Core philosophy: "Gaboleh Rugi Besar" (Never let a small loss become a big loss).
        """
        if avg_entry_price <= 0.0:
            return {"action": "HOLD", "reason": "No valid entry price"}

        pnl_pct = (current_price - avg_entry_price) / avg_entry_price

        # 1. HARD STOP LOSS (-15%)
        # If the position goes against us by 15%, cut it immediately. No hoping.
        if pnl_pct <= -0.15:
            return {"action": "STOP_LOSS", "reason": f"Hard SL hit ({pnl_pct*100:.1f}%)"}

        # 2. SIGNAL REVERSAL CUT (Fusion Engine says the trend is dead)
        # If we are slightly losing/winning but the fusion engine says the signal is trash now (< 0.3)
        if current_signal_score < 0.35 and pnl_pct < 0.05:
            return {"action": "STOP_LOSS", "reason": "Signal died, cutting exposure"}

        # 3. TRAILING TAKE PROFIT (+30% to +100%)
        # If we are up significantly, secure the bag.
        if pnl_pct >= 1.00:  # +100%
            return {"action": "TAKE_PROFIT", "reason": "Massive target reached (+100%)"}
        elif pnl_pct >= 0.30 and current_signal_score < 0.50:
            return {"action": "TAKE_PROFIT", "reason": "Momentum slowing, secured +30%"}

        # 4. TIME DECAY CUT (Don't hold a losing bag into resolution)
        if hours_remaining <= 2.0 and pnl_pct <= 0.0:
            return {"action": "TIME_CUT", "reason": "Event resolving soon, closing losing position"}

        return {"action": "HOLD", "reason": f"PnL {pnl_pct*100:.1f}%, Trend intact"}


ENGINE = PolymarketEngine()


# ============================================================
# PROBABILITY HISTORY TRACKER (v7.3)
# Track probability changes over time to detect trend shifts.
# ============================================================
_PROB_HISTORY_FILE = STATE_DIR / "polymarket_prob_history.json"
_PROB_HISTORY_MAX_ENTRIES = 288  # 24h of 5-min snapshots per market


class ProbabilityTracker:
    """Tracks market probability history for shift detection."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._history: Dict[str, List[Dict[str, Any]]] = {}  # slug → [{t, p}, ...]
        self._load()

    def _load(self) -> None:
        if _PROB_HISTORY_FILE.exists():
            try:
                raw = json.loads(_PROB_HISTORY_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._history = raw
            except Exception:
                pass

    def _save(self) -> None:
        with self._lock:
            try:
                _atomic_write(_PROB_HISTORY_FILE, self._history)
            except Exception:
                pass

    def record(self, markets: List[Dict[str, Any]]) -> None:
        """Record current probabilities for all markets."""
        now = time.time()
        with self._lock:
            for m in markets:
                slug = str(m.get("slug") or "")
                if not slug:
                    continue
                prob = _safe_float(m.get("implied_prob_yes"))
                if prob <= 0:
                    continue
                entries = self._history.setdefault(slug, [])
                entries.append({"t": now, "p": round(prob, 4)})
                # Trim old entries
                if len(entries) > _PROB_HISTORY_MAX_ENTRIES:
                    self._history[slug] = entries[-_PROB_HISTORY_MAX_ENTRIES:]
            self._save()

    def get_shift(self, slug: str, window_seconds: int = 3600) -> Optional[Dict[str, Any]]:
        """Compute probability shift for a market within time window."""
        entries = self._history.get(slug, [])
        if len(entries) < 2:
            return None
        now = time.time()
        current = entries[-1]
        # Find entry closest to (now - window)
        target_t = now - window_seconds
        baseline = None
        for e in entries:
            if e["t"] >= target_t:
                baseline = e
                break
        if baseline is None or baseline is current:
            baseline = entries[0]
        delta = current["p"] - baseline["p"]
        elapsed_h = max(0.01, (current["t"] - baseline["t"]) / 3600)
        return {
            "current": current["p"],
            "baseline": baseline["p"],
            "delta": round(delta, 4),
            "delta_per_hour": round(delta / elapsed_h, 4),
            "window_hours": round(elapsed_h, 2),
        }

    def detect_signals(self, markets: List[Dict[str, Any]], threshold: float = 0.10) -> List[Dict[str, Any]]:
        """Detect significant probability shifts across all tracked markets."""
        signals = []
        for m in markets:
            slug = str(m.get("slug") or "")
            if not slug:
                continue
            # 1-hour shift
            shift_1h = self.get_shift(slug, window_seconds=3600)
            # 24-hour shift
            shift_24h = self.get_shift(slug, window_seconds=86400)

            if shift_1h and abs(shift_1h["delta"]) >= threshold:
                signal = m.get("asset_signal") if isinstance(m.get("asset_signal"), dict) else {}
                signals.append({
                    "slug": slug,
                    "question": str(m.get("question") or "")[:120],
                    "asset": str(signal.get("asset") or ""),
                    "mapped_pair": str(signal.get("mapped_pair") or ""),
                    "shift_1h": shift_1h,
                    "shift_24h": shift_24h,
                    "direction": "BULLISH" if shift_1h["delta"] > 0 else "BEARISH",
                    "magnitude": abs(shift_1h["delta"]),
                })
        return sorted(signals, key=lambda x: x["magnitude"], reverse=True)[:10]


PROB_TRACKER = ProbabilityTracker()


def _state_payload() -> Dict[str, Any]:
    with _state_lock:
        if _cached_state:
            return dict(_cached_state)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return ENGINE.refresh_state()


class Handler(BaseHTTPRequestHandler):
    server_version = "KiBotPolymarket/1.0"

    def _json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not AUTH_TOKEN:
            return False
        return self.headers.get("Authorization", "").strip() == f"Bearer {AUTH_TOKEN}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            state = _state_payload()
            self._json(HTTPStatus.OK if state.get("ready") else HTTPStatus.BAD_GATEWAY, state)
            return
        if self.path == "/api/state":
            self._json(HTTPStatus.OK, _state_payload())
            return
        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/refresh":
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            try:
                self._json(HTTPStatus.OK, ENGINE.refresh_state())
            except Exception as error:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/order":
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body or "{}")
                result = ENGINE.place_market_order(
                    token_id=str(payload.get("token_id") or ""),
                    side=str(payload.get("side") or "BUY"),
                    amount=float(payload.get("amount") or 0.0),
                    price=float(payload.get("price") or 0.0),
                    order_type=str(payload.get("order_type") or "FAK"),
                )
                self._json(HTTPStatus.OK, {"ok": True, "result": result})
            except Exception as error:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
            return
        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[POLYMARKET] {self.address_string()} {fmt % args}", flush=True)


def _refresh_loop() -> None:
    while True:
        try:
            state = ENGINE.refresh_state()
            top = state.get("top_opportunities") if isinstance(state.get("top_opportunities"), list) else []
            print(
                f"[POLYMARKET] refresh ready={state.get('ready')} markets={state.get('gamma_market_count')} top={len(top)}",
                flush=True,
            )
        except Exception as error:
            print(f"[POLYMARKET][ERROR] refresh failed: {error}", flush=True)
        time.sleep(max(15, REFRESH_SEC))


def main() -> None:
    ENGINE.refresh_state()
    threading.Thread(target=_refresh_loop, name="kibot-polymarket-refresh", daemon=True).start()
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    print(f"[POLYMARKET] listening on {BIND_HOST}:{BIND_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
