import json
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / 'state'

class Web3SafetyChecker:
    def evaluate(self, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        score = 100
        reasons = []
        liq = float(opportunity.get('liquidity', 0) or 0)
        vol = float(opportunity.get('volume', 0) or 0)
        spread = float(opportunity.get('spread_pct', 0) or 0)
        slippage = float(opportunity.get('slippage_pct', 0) or 0)
        contract_age = float(opportunity.get('contract_age_days', 0) or 0)
        holder_conc = float(opportunity.get('holder_concentration_pct', 0) or 0)
        ev = float(opportunity.get('ev', opportunity.get('expected_value', 0) or 0) or 0)
        trade_size_idr = float(
            opportunity.get('trade_size_idr')
            or opportunity.get('max_trade_idr')
            or opportunity.get('budget_idr')
            or opportunity.get('amount_idr')
            or 0
        )
        gas_fee_idr = float(opportunity.get('gas_fee_idr') or opportunity.get('gas_floor_idr') or opportunity.get('quote_gas_idr') or 0)
        gas_mode = str(opportunity.get('gas_mode') or 'unknown').lower()
        gas_affordable = opportunity.get('gas_affordable')
        if gas_affordable is None:
            gas_affordable = True
        token_type = str(opportunity.get('token_type') or 'evm').lower()
        route_type = str(opportunity.get('route_type') or '').upper()
        route_state = opportunity.get('route_state') if isinstance(opportunity.get('route_state'), dict) else {}

        if liq <= 0 or vol <= 0:
            score -= 35; reasons.append('liquidity_or_volume_missing')
        if spread > 3.0:
            score -= 20; reasons.append('spread_too_wide')
        if slippage > 2.5:
            score -= 20; reasons.append('slippage_too_high')
        if contract_age and contract_age < 7:
            score -= 20; reasons.append('contract_too_new')
        if holder_conc and holder_conc > 35:
            score -= 20; reasons.append('holder_concentration_high')
        if token_type == 'evm':
            if opportunity.get('honeypot'):
                score = 0; reasons.append('honeypot')
            if opportunity.get('tax_pct', 0) and float(opportunity.get('tax_pct', 0)) > 15:
                score -= 30; reasons.append('tax_too_high')
        if token_type == 'solana':
            if opportunity.get('mint_authority_enabled'):
                score -= 25; reasons.append('mint_authority_enabled')
            if opportunity.get('freeze_authority_enabled'):
                score -= 25; reasons.append('freeze_authority_enabled')
            if gas_fee_idr > 0 and trade_size_idr > 0:
                gas_ratio = gas_fee_idr / max(trade_size_idr, 1.0)
                if gas_ratio >= 0.10:
                    score -= 20; reasons.append('gas_fee_ratio_high')
                if gas_ratio >= 0.25:
                    score -= 25; reasons.append('gas_fee_dominates_trade')
                if gas_ratio >= 0.50:
                    score = 0
                    reasons.append('gas_fee_exceeds_trade_budget')
            if gas_mode == 'gasless' and trade_size_idr > 0 and gas_fee_idr > trade_size_idr * 0.10:
                score = 0
                reasons.append('gasless_surcharge_exceeds_10pct_cap')
            if gas_affordable is False:
                score = 0
                reasons.append(str(opportunity.get('gas_reason') or 'gas_unaffordable'))
            if route_type == 'PUMPFUN_BONDING_CURVE':
                if not bool(route_state.get('sell_route_available', False)):
                    score = 0
                    reasons.append('no_exit_route')
                if float(opportunity.get('age_seconds', 0) or 0) < 180:
                    score -= 10; reasons.append('bonding_curve_too_fresh')
                if float(opportunity.get('liquidity_usd', 0) or 0) < 10000:
                    score -= 15; reasons.append('bonding_curve_liquidity_thin')
            if route_type == 'UNSUPPORTED':
                score = 0; reasons.append('unsupported_route')
        if str(opportunity.get('blacklisted', False)).lower() in {'1','true','yes'}:
            score = 0; reasons.append('blacklisted')
        if ev <= 0:
            score = min(score, 30); reasons.append('negative_ev')
        if gas_fee_idr > 0 and trade_size_idr > 0 and route_type in {'JUPITER_ROUTABLE', 'PUMPFUN_AMM_OR_GRADUATED', 'BASE_SWAP'}:
            if gas_fee_idr / max(trade_size_idr, 1.0) >= 0.20:
                reasons.append('fee_floor_high_vs_trade_size')
                score = min(score, 40)

        score = max(0, min(100, score))
        passed = score >= 70 and ev > 0 and 'honeypot' not in reasons and 'blacklisted' not in reasons and 'no_exit_route' not in reasons and 'unsupported_route' not in reasons and 'gas_fee_exceeds_trade_budget' not in reasons
        max_trade_base = int(opportunity.get('max_trade_idr') or max(0, min(50000, score * 1000))) if passed else 0
        if passed and gas_fee_idr > 0:
            max_trade_base = max(0, int(max_trade_base - gas_fee_idr))
        return {
            'passed': passed,
            'score': score,
            'reason': ';'.join(reasons) if reasons else 'ok',
            'max_trade_idr': max_trade_base,
            'gas_fee_idr': gas_fee_idr,
            'gas_mode': gas_mode,
            'gas_affordable': bool(gas_affordable),
        }
