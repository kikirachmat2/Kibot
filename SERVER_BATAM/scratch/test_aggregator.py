import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR.parent))

from SERVER_BATAM.Core_Logic.council_data_aggregator import CouncilDataAggregator
from unittest.mock import MagicMock

# Mock master node
master = MagicMock()
master.last_state = {"portfolio": {"equity_idr": 1500000, "daily_pnl": "+2.5%"}}
master.market_mood = "BULLISH"

aggregator = CouncilDataAggregator(master)
context = aggregator.get_debate_context()

print("Context Tier:", context['session_tier'])
print("Market Mood:", context['market_context']['mood'])
print("Total Rejections (24h):", context['audit_data']['rejection_analysis']['total'])
print("Missed Opps Count:", len(context['audit_data']['missed_opportunities']))
if context['audit_data']['missed_opportunities']:
    print("Top Missed Opp:", context['audit_data']['missed_opportunities'][0])
