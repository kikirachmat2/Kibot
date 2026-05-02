package com.kibot.macengine.runtime

import com.kibot.core.EntryHealthDecision
import com.kibot.core.RiskDecision
import com.kibot.core.StrategyCycleResult
import com.kibot.shared.models.BotId
import com.kibot.shared.models.BotMode
import com.kibot.shared.models.BotModeSnapshot
import com.kibot.shared.models.DecimalValue
import com.kibot.shared.models.DistrustLabel
import com.kibot.shared.models.EdgeConfidence
import com.kibot.shared.models.MarketOpportunitySnapshot
import com.kibot.shared.models.MarketRegime
import com.kibot.shared.models.PairId
import com.kibot.shared.models.PairScore
import com.kibot.shared.models.PortfolioSnapshot
import com.kibot.shared.models.ProfitProtectionStatus
import com.kibot.shared.models.RiskLadderLevel
import com.kibot.shared.models.SyncHealth
import com.kibot.shared.models.TradingHorizon
import kotlinx.datetime.Instant
import kotlinx.datetime.TimeZone
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DailyTargetPursuitTest {
    private val brain = DailyTargetPursuitBrain()

    @Test
    fun hourlyEvaluationAppearsAfterFirstHour() {
        val pursuit = brain.evaluate(
            cycle = cycle(realizedPnlIdr = 500.0, unrealizedPnlIdr = 0.0),
            adaptiveAiPolicy = null,
            now = Instant.parse("2026-03-26T01:10:00Z"),
            timeZone = TimeZone.UTC,
        )

        assertTrue(pursuit.rationale.any { it.contains("Evaluasi 1 jam ke-1") })
    }

    @Test
    fun threeHourCheckpointMissIsExplicitAndRaisesUrgency() {
        val pursuit = brain.evaluate(
            cycle = cycle(realizedPnlIdr = 0.0, unrealizedPnlIdr = 0.0),
            adaptiveAiPolicy = null,
            now = Instant.parse("2026-03-26T03:05:00Z"),
            timeZone = TimeZone.UTC,
        )

        assertTrue(pursuit.rationale.any { it.contains("Checkpoint 3 jam ke-1 miss") })
        assertTrue(pursuit.urgency >= 0.24)
    }

    @Test
    fun hourlyMissProducesEscalationState() {
        val pursuit = brain.evaluate(
            cycle = cycle(realizedPnlIdr = 0.0, unrealizedPnlIdr = 0.0),
            adaptiveAiPolicy = null,
            now = Instant.parse("2026-03-26T02:10:00Z"),
            timeZone = TimeZone.UTC,
        )

        assertTrue(pursuit.hourlyMissed)
        assertTrue(pursuit.hourlyEscalationLevel >= 1)
        assertTrue(pursuit.hourlyShortfallPct > 0.0)
    }

    @Test
    fun sixHourCheckpointRecursAsSecondWindow() {
        val pursuit = brain.evaluate(
            cycle = cycle(realizedPnlIdr = 0.0, unrealizedPnlIdr = 0.0),
            adaptiveAiPolicy = null,
            now = Instant.parse("2026-03-26T06:05:00Z"),
            timeZone = TimeZone.UTC,
        )

        assertEquals(2, pursuit.checkpointWindowIndex)
        assertTrue(pursuit.checkpointMissed)
        assertTrue(pursuit.checkpointEscalationLevel >= 2)
    }

    @Test
    fun unrealizedOnlyTargetDoesNotUnlockTargetSatisfied() {
        val pursuit = brain.evaluate(
            cycle = cycle(realizedPnlIdr = 0.0, unrealizedPnlIdr = 60_000.0),
            adaptiveAiPolicy = null,
            now = Instant.parse("2026-03-26T20:00:00Z"),
            timeZone = TimeZone.UTC,
        )

        assertFalse(pursuit.targetSatisfied)
    }

    private fun cycle(realizedPnlIdr: Double, unrealizedPnlIdr: Double): StrategyCycleResult {
        val opening = 100_000.0
        val current = opening + realizedPnlIdr + unrealizedPnlIdr
        return StrategyCycleResult(
            portfolio = PortfolioSnapshot(
                botId = BotId("main"),
                balances = emptyList(),
                openOrders = emptyList(),
                positions = emptyList(),
                totalEquityIdr = DecimalValue.fromDouble(current),
                lastSyncedAt = Instant.parse("2026-03-26T00:00:00Z"),
            ),
            dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
                openingEquityIdr = DecimalValue.fromDouble(opening),
                currentEquityIdr = DecimalValue.fromDouble(current),
                realizedPnlIdr = DecimalValue.fromDouble(realizedPnlIdr),
                unrealizedPnlIdr = DecimalValue.fromDouble(unrealizedPnlIdr),
                drawdownPct = 0.0,
                hardDailyLossLimitPct = 0.25,
                hardStopTriggered = false,
                rebasePending = false,
                riskLadderLevel = RiskLadderLevel.NORMAL,
                highWatermarkEquityIdr = DecimalValue.fromDouble(current),
                givebackPct = 0.0,
                profitProtectionStatus = ProfitProtectionStatus.INACTIVE,
            ),
            rankedPairs = listOf(
                PairScore(
                    pairId = PairId("xrp_idr"),
                    liquidityScore = 0.7,
                    spreadScore = 0.7,
                    slippageScore = 0.7,
                    stabilityScore = 0.7,
                    volumeConsistencyScore = 0.7,
                    volatilityQualityScore = 0.7,
                    trendQualityScore = 0.72,
                    historicalExpectancyScore = 0.7,
                    recentHealthScore = 0.7,
                    fillQualityScore = 0.7,
                    holdabilityScore = 0.7,
                    feeAdjustedEdgeScore = 1.6,
                    marketOpportunityScore = 0.72,
                    rankingScore = 0.74,
                    preferredHorizon = TradingHorizon.TACTICAL,
                    allowed = true,
                ),
            ),
            marketSnapshot = MarketOpportunitySnapshot(
                regime = MarketRegime.HEALTHY_UPTREND,
                marketOpportunityScore = 0.72,
                botHealthScore = 0.8,
                performanceMomentumScore = 0.6,
                edgeConfidence = EdgeConfidence.HIGH,
                tacticalBiasScore = 0.7,
                swingBiasScore = 0.55,
                opportunityAvailabilityScore = 0.7,
                microstructureHealthScore = 0.72,
            ),
            healthDecision = EntryHealthDecision(
                tradingAllowed = true,
                shouldSuggestTakeover = false,
                reasons = emptyList(),
            ),
            riskDecision = RiskDecision(
                allowNewEntries = true,
                hardStopTriggered = false,
                maxAllowedAdditionalPositions = 2,
                suggestedPerPositionBudgetIdr = 25_000.0,
                riskLadderLevel = RiskLadderLevel.NORMAL,
                suggestedModeFloor = BotMode.ATTACK,
                profitProtectionStatus = ProfitProtectionStatus.INACTIVE,
                dailyProfitLockActive = false,
                sizeMultiplier = 1.0,
                deploymentMultiplier = 1.0,
                reasons = emptyList(),
            ),
            modeSnapshot = BotModeSnapshot(
                mode = BotMode.ATTACK,
                edgeConfidence = EdgeConfidence.HIGH,
                aggressionScore = 0.85,
                riskLadderLevel = RiskLadderLevel.NORMAL,
                profitProtectionStatus = ProfitProtectionStatus.INACTIVE,
                tacticalBiasScore = 0.72,
                swingBiasScore = 0.58,
                tradingAllowed = true,
            ),
            deploymentPlan = com.kibot.shared.models.CapitalDeploymentPlan(
                allowNewEntries = true,
                allowRotation = true,
                maxActivePositions = 2,
                suggestedPerPositionBudgetIdr = 25_000.0,
                targetCashReservePct = 0.05,
                capitalUtilizationTargetPct = 0.95,
                preferredHorizon = TradingHorizon.TACTICAL,
                candidates = listOf(
                    com.kibot.shared.models.CandidateOpportunity(
                        pairId = PairId("xrp_idr"),
                        tier = com.kibot.shared.models.PairTier.TIER_A,
                        preferredHorizon = TradingHorizon.TACTICAL,
                        rankingScore = 0.74,
                        marketOpportunityScore = 0.72,
                        expectedNetProfitabilityPct = 1.9,
                        holdabilityScore = 0.7,
                    ),
                ),
            ),
            selectedSignal = null,
            executionPlan = null,
            topCandidate = PairId("xrp_idr"),
            distrustLabels = emptyList<DistrustLabel>(),
            summary = emptyList(),
        )
    }
}
