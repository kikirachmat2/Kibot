from Core.Web3.web3_opportunity_scanner import Web3OpportunityScanner
from Core.Web3.web3_executor_guard import Web3ExecutorGuard
from Core.Web3.web3_quote_router import Web3QuoteRouter
from Core.Web3.web3_safety_checker import Web3SafetyChecker
from Core.Treasury.phantom_multichain_controller import PhantomMultichainController


def test_web3_runtime_classes_import_and_connect():
    scanner = Web3OpportunityScanner()
    guard = Web3ExecutorGuard()
    quote = Web3QuoteRouter()
    safety = Web3SafetyChecker()
    controller = PhantomMultichainController()

    assert scanner is not None
    assert guard is not None
    assert quote is not None
    assert safety is not None
    assert controller.get_route("solana").get("status") in {"LIVE_READY", "BLOCKED", "SCOUTING"}

