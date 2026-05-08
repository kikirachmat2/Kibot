package com.kibot.macengine.runtime

import com.kibot.core.ManagedPosition
import com.kibot.core.PositionStrategy
import com.kibot.core.TradeRecord
import com.kibot.shared.models.AiPairSupportHint
import com.kibot.shared.models.DecimalValue
import com.kibot.shared.models.MarketRegime
import com.kibot.shared.models.PairId
import com.kibot.shared.models.PairTier
import com.kibot.shared.models.SetupType
import com.kibot.shared.models.TradingHorizon
import kotlinx.datetime.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AutonomousAiReviewBuilderTest {
    @Test
    fun redDayBuildsProtectiveAdaptivePolicy() {
        val now = Instant.parse("2026-04-08T11:30:00Z")
        val output = AutonomousAiReviewBuilder.build(
            input = AutonomousAiReviewInput(
                now = now,
                botId = "KiBot",
                topCandidate = PairId("fartcoin_idr"),
                marketRegime = MarketRegime.HIGH_VOLATILITY_MOMENTUM,
                freeIdr = 62_508.0,
                dailyPnlPct = -3.9,
                holdings = listOf(
                    managedPosition(pairId = "drx_idr", pnlPct = -2.4, openedAt = Instant.parse("2026-04-08T04:00:00Z")),
                    managedPosition(pairId = "doge_idr", pnlPct = 2.8, openedAt = Instant.parse("2026-04-08T09:00:00Z")),
                ),
                aiHints = listOf(
                    AiPairSupportHint(
                        pairId = PairId("fartcoin_idr"),
                        supportBias = 0.06,
                        cautionBias = 0.01,
                        cheapNominalWatch = false,
                        rationale = "Momentum bersih dan depth sehat.",
                        generatedAt = now,
                    ),
                ),
                aiUsedNetwork = true,
                aiBlockedReason = null,
                recentTrades = listOf(
                    tradeRecord(pair = "drx_idr", netProfitIdr = -1400.0, netProfitPct = -2.4),
                    tradeRecord(pair = "arc_idr", netProfitIdr = -650.0, netProfitPct = -1.1),
                    tradeRecord(pair = "zec_idr", netProfitIdr = 480.0, netProfitPct = 0.9),
                ),
            ),
            adaptivePolicyPath = "/tmp/adaptive_policy.json",
        )

        assertEquals(listOf("gemini"), output.summary.successful_providers)
        assertTrue(output.policy.execution.rotateNowPairs.contains("drx_idr"))
        assertTrue(output.policy.execution.holdLongerPairs.contains("doge_idr"))
        assertEquals(null, output.policy.execution.concentrationPair)
        assertTrue(output.policy.adjustments.partialTakeProfitPnlDelta <= -0.45)
        assertTrue(output.policy.execution.forceMarketPairs.isEmpty())
        assertTrue(output.policy.adjustments.extraSlotsDelta <= -1)
        assertTrue(output.policy.watchdog.forceRotation)
    }

    private fun managedPosition(
        pairId: String,
        pnlPct: Double,
        openedAt: Instant,
    ): ManagedPosition {
        return ManagedPosition(
            pairId = PairId(pairId),
            quantity = DecimalValue.fromDouble(100.0),
            averageEntryPrice = DecimalValue.fromDouble(100.0),
            currentBidPrice = DecimalValue.fromDouble(if (pnlPct >= 0.0) 102.0 else 97.0),
            currentValueIdr = DecimalValue.fromDouble(10_000.0),
            unrealizedPnlIdr = DecimalValue.fromDouble(10_000.0 * pnlPct / 100.0),
            unrealizedPnlPct = pnlPct,
            breakEvenPrice = DecimalValue.fromDouble(100.6),
            takeProfitPrice = DecimalValue.fromDouble(103.0),
            stopPrice = DecimalValue.fromDouble(97.0),
            openedAt = openedAt,
            updatedAt = openedAt,
            horizon = TradingHorizon.TACTICAL,
            setupType = SetupType.LIGHT_BREAKOUT_CONTINUATION,
            pairTier = PairTier.TIER_B,
            speculativePocket = false,
            expectedHoldingHours = 1.0,
        )
    }

    private fun tradeRecord(
        pair: String,
        netProfitIdr: Double,
        netProfitPct: Double,
    ): TradeRecord {
        return TradeRecord(
            id = 1,
            timestamp = Instant.parse("2026-04-08T10:00:00Z"),
            pair = pair,
            strategy = PositionStrategy.STABLE,
            entryPrice = 100.0,
            exitPrice = 101.0,
            quantity = 100.0,
            entryFeeIdr = 30.0,
            exitFeeIdr = 30.0,
            totalFeeIdr = 60.0,
            slippageIdr = 0.0,
            totalCostIdr = 60.0,
            netProfitIdr = netProfitIdr,
            netProfitPct = netProfitPct,
            holdMinutes = 35.0,
            exitReason = "test",
        )
    }
}
