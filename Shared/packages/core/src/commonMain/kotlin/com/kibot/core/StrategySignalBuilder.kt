package com.kibot.core

import com.kibot.shared.models.*
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant

/**
 * Encapsulates the signal building, scoring, and execution planning logic for [StrategyOrchestrator].
 * Extracted to reduce the complexity of the main orchestrator.
 */
internal class StrategySignalBuilder(
    private val executionConfig: StrategyExecutionConfig,
    private var riskConfig: RiskConfig,
    private val vetoService: VetoService
) {

    fun updateRiskConfig(newConfig: RiskConfig) {
        this.riskConfig = newConfig
    }

    fun buildSignals(
        rankedPairs: List<PairScore>,
        quoteByPair: Map<PairId, MarketQuote>,
        marketQuotes: List<MarketQuote>,
        balances: List<BalanceSnapshot>,
        positions: List<PositionSnapshot>,
        marketSnapshot: MarketOpportunitySnapshot,
        modeSnapshot: BotModeSnapshot,
        deploymentPlan: CapitalDeploymentPlan,
        openOrders: List<OrderSnapshot>,
        weeklySummary: WeeklyLearningSummary?,
        dailyRisk: DailyRiskSnapshot?,
        observedAtEpochMs: Long,
        leadLagSignal: LeadLagSelectionSignal?,
        aiSoftAuditOnly: Boolean,
        aiConsensus: Double?,
        selectionContext: PairSelectionContext,
        coolingPairs: Set<PairId> = emptySet(),
    ): List<StrategySignal> {
        if (!modeSnapshot.tradingAllowed || (!deploymentPlan.allowNewEntries && !deploymentPlan.allowRotation)) return emptyList()
        if (marketSnapshot.regime == MarketRegime.BREAKDOWN_PANIC) return emptyList()

        val urgentEntryMode = leadLagSignal != null &&
            !leadLagSignal.fatigue &&
            leadLagSignal.leadMomentumScore >= 0.80

        val pendingBuyPairs = openOrders
            .asSequence()
            .filter { it.side == OrderSide.BUY && it.status in activeBuyOrderStatuses }
            .map { it.pairId }
            .toSet()

        val heldPairs = positions
            .filter { it.state != PositionState.CLOSED }
            .map { it.pairId }
            .toSet()

        val rotationFundingAllowed = deploymentPlan.allowRotation && heldPairs.isNotEmpty()
        val parallelMomentumBiasActive = marketSnapshot.regime == MarketRegime.HIGH_VOLATILITY_MOMENTUM &&
            deploymentPlan.allowNewEntries &&
            deploymentPlan.maxActivePositions > heldPairs.size &&
            deploymentPlan.suggestedPerPositionBudgetIdr >= executionConfig.minOrderNotionalIdr

        val thresholds = resolveEntryThresholds(
            modeSnapshot = modeSnapshot,
            marketSnapshot = marketSnapshot,
            heldPairs = heldPairs,
            weeklySummary = weeklySummary,
            dailyRisk = dailyRisk,
            urgentEntryMode = urgentEntryMode,
            parallelMomentumBiasActive = parallelMomentumBiasActive,
        )

        if (thresholds.dailyProfitLockActive) return emptyList()

        val dominantPairId = deploymentPlan.candidates
            .take(2)
            .let { topCandidates ->
                val first = topCandidates.firstOrNull()
                val second = topCandidates.getOrNull(1)
                if (first != null && (second == null || (first.rankingScore - second.rankingScore) >= 0.07)) {
                    first.pairId
                } else {
                    null
                }
            }

        val scoreFloor = 0.0
        val chosenCandidates = deploymentPlan.candidates
            .take(executionConfig.candidateCount)
            .mapNotNull { candidate ->
                val pairScore = rankedPairs.firstOrNull { it.pairId == candidate.pairId } ?: return@mapNotNull null
                val quote = quoteByPair[candidate.pairId] ?: return@mapNotNull null
                val pairAssets = candidate.pairId.assets()
                if (pairAssets.quoteAsset !in executionConfig.executionAllowedQuoteAssets) return@mapNotNull null

                val hasFunding = hasFundedQuoteAsset(
                    pairId = candidate.pairId,
                    balances = balances,
                    marketQuotes = marketQuotes,
                    targetBudgetIdr = deploymentPlan.suggestedPerPositionBudgetIdr,
                )

                if (candidate.pairId in heldPairs || candidate.pairId in pendingBuyPairs) return@mapNotNull null
                if (!hasFunding && !rotationFundingAllowed) return@mapNotNull null
                
                if (candidate.pairId in coolingPairs) return@mapNotNull null

                if (!selectionContext.bypassVetoService && vetoService.shouldVetoEntry(
                        candidate = pairScore,
                        quote = quote,
                        leadLagSignal = leadLagSignal,
                        priceBandAllowed = true,
                        softAuditOnly = aiSoftAuditOnly,
                        aiConsensus = aiConsensus,
                    )
                ) {
                    return@mapNotNull null
                }

                val setupReadiness = deriveSetupReadiness(
                    pairScore = pairScore,
                    quote = quote,
                    marketSnapshot = marketSnapshot,
                    baseOpportunityFloor = thresholds.minOpportunityScore,
                    urgentEntryMode = urgentEntryMode,
                    parallelMomentumBiasActive = thresholds.parallelMomentumBiasActive,
                ) ?: return@mapNotNull null

                if (!selectionContext.bypassRankingFloor && pairScore.rankingScore < thresholds.minRankingScore) return@mapNotNull null

                val selectionScore = scoreEntryCandidate(
                    pairScore = pairScore,
                    quote = quote,
                    marketSnapshot = marketSnapshot,
                    modeSnapshot = modeSnapshot,
                    setupReadiness = setupReadiness,
                    dominantPairId = dominantPairId,
                    targetBudgetIdr = deploymentPlan.suggestedPerPositionBudgetIdr,
                    weeklySummary = weeklySummary,
                    dailyProfitLockActive = thresholds.dailyProfitLockActive,
                    leadLagSignal = leadLagSignal,
                    aiSoftAuditOnly = aiSoftAuditOnly,
                    urgentEntryMode = urgentEntryMode,
                )
                if (selectionScore < scoreFloor) return@mapNotNull null

                CandidateSelection(
                    pairScore = pairScore,
                    quote = quote,
                    setupReadiness = setupReadiness,
                    selectionScore = selectionScore,
                )
            }
            .sortedByDescending { it.selectionScore }
            .take(executionConfig.maxExecutableEntriesPerCycle)

        return chosenCandidates.map { candidate ->
            buildSignalFromCandidate(
                candidate = candidate,
                marketSnapshot = marketSnapshot,
                modeSnapshot = modeSnapshot,
                dominantPairId = dominantPairId,
                productiveIdleBiasActive = thresholds.productiveIdleBiasActive,
                parallelMomentumBiasActive = thresholds.parallelMomentumBiasActive,
                leadLagSignal = leadLagSignal,
                aiSoftAuditOnly = aiSoftAuditOnly,
            )
        }
    }

    private fun resolveEntryThresholds(
        modeSnapshot: BotModeSnapshot,
        marketSnapshot: MarketOpportunitySnapshot,
        heldPairs: Set<PairId>,
        weeklySummary: WeeklyLearningSummary? = null,
        dailyRisk: DailyRiskSnapshot? = null,
        urgentEntryMode: Boolean = false,
        parallelMomentumBiasActive: Boolean = false,
    ): EntryThresholds {
        val baseRankingScore = when (modeSnapshot.mode) {
            BotMode.SAFE -> Double.MAX_VALUE
            BotMode.DEFENSIVE -> executionConfig.defensiveMinRankingScore
            BotMode.GROWTH -> executionConfig.growthMinRankingScore
            BotMode.ATTACK -> executionConfig.attackMinRankingScore
        }
        val dailyProfitLockActive = dailyRisk?.let { risk ->
            val opening = risk.openingEquityIdr.toDoubleOrZero().coerceAtLeast(1.0)
            val current = risk.currentEquityIdr.toDoubleOrZero().coerceAtLeast(0.0)
            ((current - opening) / opening) * 100.0 >= riskConfig.dailyProfitLockPct * 100.0
        } ?: false
        val productiveIdleBiasActive = heldPairs.isEmpty() &&
            modeSnapshot.mode in setOf(BotMode.GROWTH, BotMode.ATTACK) &&
            marketSnapshot.regime != MarketRegime.BREAKDOWN_PANIC &&
            marketSnapshot.marketOpportunityScore >= 0.57
        val adaptiveParallelBiasActive = productiveIdleBiasActive || parallelMomentumBiasActive
        val learningAggressionBias = when {
            weeklySummary == null -> 0.0
            weeklySummary.falseEntryRate <= 0.18 &&
                weeklySummary.productiveUtilizationPct <= 0.30 &&
                weeklySummary.missedOpportunityRate >= 0.20 -> 0.02
            weeklySummary.falseEntryRate <= 0.24 &&
                weeklySummary.productiveUtilizationPct <= 0.36 &&
                weeklySummary.missedOpportunityRate >= 0.14 -> 0.01
            else -> 0.0
        }
        val breakoutIdleBias = if (
            adaptiveParallelBiasActive &&
            marketSnapshot.marketOpportunityScore >= 0.62 &&
            marketSnapshot.regime != MarketRegime.BREAKDOWN_PANIC
        ) {
            0.03
        } else {
            0.0
        }
        val parallelMomentumRankingBias = if (parallelMomentumBiasActive) 0.05 else 0.0
        val parallelMomentumOpportunityBias = if (parallelMomentumBiasActive) 0.05 else 0.0
        val urgentRankingBias = if (urgentEntryMode) 0.06 else 0.0
        val urgentOpportunityBias = if (urgentEntryMode) 0.05 else 0.0
        val lockRankingFloor = if (dailyProfitLockActive) riskConfig.dailyProfitLockRankingScore else 0.0
        val lockOpportunityFloor = if (dailyProfitLockActive) riskConfig.dailyProfitLockOpportunityScore else 0.0
        return EntryThresholds(
            minRankingScore = (
                baseRankingScore -
                    (if (adaptiveParallelBiasActive) executionConfig.productiveIdleRankingDelta else 0.0) -
                    learningAggressionBias -
                    breakoutIdleBias -
                    urgentRankingBias -
                    parallelMomentumRankingBias
                ).coerceAtLeast(lockRankingFloor),
            minOpportunityScore = (
                executionConfig.minExpectedOpportunityScore -
                    (if (adaptiveParallelBiasActive) executionConfig.productiveIdleOpportunityDelta else 0.0) -
                    (learningAggressionBias * 0.75) -
                    (breakoutIdleBias * 0.70) -
                    urgentOpportunityBias -
                    parallelMomentumOpportunityBias
                ).coerceAtLeast(lockOpportunityFloor),
            productiveIdleBiasActive = productiveIdleBiasActive,
            parallelMomentumBiasActive = parallelMomentumBiasActive,
            dailyProfitLockActive = dailyProfitLockActive,
        )
    }

    private fun deriveSetupReadiness(
        pairScore: PairScore,
        quote: MarketQuote,
        marketSnapshot: MarketOpportunitySnapshot,
        baseOpportunityFloor: Double,
        urgentEntryMode: Boolean = false,
        parallelMomentumBiasActive: Boolean = false,
    ): SetupReadiness? {
        val setupType: SetupType
        val signalType: StrategySignalType
        val adjustedOpportunityFloor: Double
        val expectedHoldingHours: Double
        val rationale: String

        when {
            parallelMomentumBiasActive &&
                marketSnapshot.regime == MarketRegime.HIGH_VOLATILITY_MOMENTUM &&
                quote.spreadPct <= 1.0 &&
                quote.estimatedSlippagePct <= 1.0 &&
                quote.bidDepthTop5Idr.toDoubleOrZero() >= 25_000.0 &&
                quote.askDepthTop5Idr.toDoubleOrZero() >= 25_000.0 &&
                quote.orderBookStabilityScore >= 0.42 &&
                pairScore.fillQualityScore >= 0.44 &&
                pairScore.trendQualityScore >= 0.46 &&
                quote.recentTradeActivityScore >= 0.42 &&
                pairScore.feeAdjustedEdgeScore >= -0.05 -> {
                setupType = SetupType.LIGHT_BREAKOUT_CONTINUATION
                signalType = StrategySignalType.BREAKOUT_ENTRY
                adjustedOpportunityFloor = (baseOpportunityFloor - if (urgentEntryMode) 0.10 else 0.08).coerceAtLeast(0.0)
                expectedHoldingHours = 8.0
                rationale = "Slot paralel momentum aktif: spread, slippage, dan depth masih aman, jadi entry kedua boleh ikut arus tanpa menunggu posisi lama selesai."
            }

            pairScore.speculativePocket &&
                marketSnapshot.regime != MarketRegime.BREAKDOWN_PANIC &&
                speculativePocketAllowed(marketSnapshot) &&
                quote.shortTermReturnPct in executionConfig.breakoutAggressiveEntryMinShortTermReturnPct..220.0 &&
                quote.mediumTermReturnPct >= executionConfig.breakoutAggressiveEntryMinMediumTermReturnPct &&
                pairScore.fillQualityScore >= 0.58 &&
                pairScore.trendQualityScore >= 0.60 &&
                quote.recentTradeActivityScore >= 0.56 &&
                pairScore.feeAdjustedEdgeScore >= (executionConfig.breakoutAggressiveEntryMinExpectedNetProfitPct - 0.04) -> {
                setupType = SetupType.LIGHT_BREAKOUT_CONTINUATION
                signalType = StrategySignalType.BREAKOUT_ENTRY
                adjustedOpportunityFloor = (baseOpportunityFloor - if (urgentEntryMode) 0.055 else 0.035).coerceAtLeast(0.0)
                expectedHoldingHours = 10.0
                rationale = "Sleeve spekulatif aktif: momentum breakout terlihat dominan, jadi bot boleh lebih cepat masuk dan winner diberi ruang lebih panjang."
            }

            quote.shortTermReturnPct >= executionConfig.breakoutAggressiveEntryMinShortTermReturnPct &&
                quote.mediumTermReturnPct >= executionConfig.breakoutAggressiveEntryMinMediumTermReturnPct &&
                pairScore.fillQualityScore >= 0.60 &&
                pairScore.trendQualityScore >= 0.62 &&
                quote.recentTradeActivityScore >= 0.58 &&
                pairScore.feeAdjustedEdgeScore >= executionConfig.breakoutAggressiveEntryMinExpectedNetProfitPct -> {
                setupType = SetupType.LIGHT_BREAKOUT_CONTINUATION
                signalType = StrategySignalType.BREAKOUT_ENTRY
                adjustedOpportunityFloor = when (marketSnapshot.regime) {
                    MarketRegime.HIGH_VOLATILITY_MOMENTUM -> (baseOpportunityFloor - if (urgentEntryMode) 0.060 else 0.040)
                    MarketRegime.HEALTHY_UPTREND -> (baseOpportunityFloor - if (urgentEntryMode) 0.045 else 0.025)
                    MarketRegime.HEALTHY_SIDEWAYS -> (baseOpportunityFloor - if (urgentEntryMode) 0.030 else 0.015)
                    else -> baseOpportunityFloor
                }.coerceAtLeast(0.0)
                expectedHoldingHours = if (pairScore.preferredHorizon == TradingHorizon.SWING) 30.0 else 12.0
                rationale = if (marketSnapshot.regime == MarketRegime.HIGH_VOLATILITY_MOMENTUM) {
                    "Momentum override aktif: volatilitas tinggi dibaca sebagai arus searah, jadi breakout boleh dieksekusi selama spread dan depth tetap sehat."
                } else {
                    "Momentum eksplosif terlihat bersih, jadi bot boleh ambil breakout lebih tegas selama net edge tetap masuk akal."
                }
            }

            pairScore.preferredHorizon == TradingHorizon.SWING &&
                marketSnapshot.regime == MarketRegime.HEALTHY_UPTREND &&
                pairScore.holdabilityScore >= 0.64 &&
                pairScore.trendQualityScore >= 0.60 &&
                quote.mediumTermReturnPct >= 0.90 -> {
                setupType = SetupType.SWING_TREND_CONTINUATION
                signalType = StrategySignalType.BREAKOUT_ENTRY
                adjustedOpportunityFloor = (baseOpportunityFloor - if (urgentEntryMode) 0.03 else 0.01).coerceAtLeast(0.0)
                expectedHoldingHours = 72.0
                rationale = "Regime uptrend dan holdability kuat, jadi swing continuation boleh diprioritaskan."
            }

            quote.spreadPct <= 0.38 &&
                quote.estimatedSlippagePct <= 0.38 &&
                pairScore.fillQualityScore >= 0.58 &&
                quote.shortTermReturnPct <= 0.90 &&
                marketSnapshot.regime != MarketRegime.BREAKDOWN_PANIC -> {
                setupType = SetupType.HEALTHY_SHORT_TERM_PULLBACK
                signalType = StrategySignalType.MEAN_REVERSION_ENTRY
                adjustedOpportunityFloor = (baseOpportunityFloor - if (urgentEntryMode) 0.05 else 0.03).coerceAtLeast(0.0)
                expectedHoldingHours = 7.0
                rationale = "Spread dan fill sehat, jadi pullback taktis boleh dipakai saat harga sedang rehat sehat."
            }

            quote.shortTermReturnPct in -3.8..-0.35 &&
                quote.mediumTermReturnPct >= 0.75 &&
                pairScore.trendQualityScore >= 0.57 &&
                pairScore.fillQualityScore >= 0.58 &&
                quote.recentTradeActivityScore >= 0.54 &&
                pairScore.feeAdjustedEdgeScore >= 0.40 &&
                marketSnapshot.regime != MarketRegime.BREAKDOWN_PANIC -> {
                setupType = SetupType.HEALTHY_SHORT_TERM_PULLBACK
                signalType = StrategySignalType.MEAN_REVERSION_ENTRY
                adjustedOpportunityFloor = (baseOpportunityFloor - if (urgentEntryMode) 0.04 else 0.02).coerceAtLeast(0.0)
                expectedHoldingHours = 9.0
                rationale = "Harga sedang pullback jangka pendek tapi tren menengah tetap sehat, jadi bot boleh akumulasi bertahap saat diskon."
            }

            quote.mediumTermReturnPct >= 0.70 &&
                quote.shortTermReturnPct >= 0.18 -> {
                setupType = SetupType.LIGHT_BREAKOUT_CONTINUATION
                signalType = StrategySignalType.BREAKOUT_ENTRY
                adjustedOpportunityFloor = when (marketSnapshot.regime) {
                    MarketRegime.HEALTHY_SIDEWAYS -> baseOpportunityFloor + if (urgentEntryMode) 0.0 else 0.015
                    MarketRegime.HIGH_VOLATILITY_UNCLEAR -> baseOpportunityFloor + if (urgentEntryMode) 0.015 else 0.03
                    MarketRegime.HIGH_VOLATILITY_MOMENTUM -> (baseOpportunityFloor - if (urgentEntryMode) 0.020 else 0.005)
                    else -> baseOpportunityFloor
                }.coerceAtMost(1.0)
                expectedHoldingHours = if (pairScore.preferredHorizon == TradingHorizon.SWING) 48.0 else 10.0
                rationale = if (marketSnapshot.regime == MarketRegime.HIGH_VOLATILITY_MOMENTUM) {
                    "Breakout continuation diprioritaskan karena arus momentum sudah jelas, jadi threshold dibuka sedikit tanpa melepas guard spread/depth."
                } else {
                    "Breakout continuation tetap boleh, tapi threshold diperketat saat market belum benar-benar nyaman."
                }
            }

            else -> return null
        }

        if (pairScore.marketOpportunityScore < adjustedOpportunityFloor) return null
        return SetupReadiness(
            setupType = setupType,
            signalType = signalType,
            expectedHoldingHours = expectedHoldingHours,
            rationale = rationale,
        )
    }

    private fun scoreEntryCandidate(
        pairScore: PairScore,
        quote: MarketQuote,
        marketSnapshot: MarketOpportunitySnapshot,
        modeSnapshot: BotModeSnapshot,
        setupReadiness: SetupReadiness,
        dominantPairId: PairId?,
        targetBudgetIdr: Double,
        weeklySummary: WeeklyLearningSummary?,
        dailyProfitLockActive: Boolean,
        leadLagSignal: LeadLagSelectionSignal?,
        aiSoftAuditOnly: Boolean,
        urgentEntryMode: Boolean,
    ): Double {
        val regimeBias = when {
            setupReadiness.setupType == SetupType.SWING_TREND_CONTINUATION ->
                ((marketSnapshot.swingBiasScore - 0.50) * 0.10).coerceIn(-0.03, 0.03)
            setupReadiness.signalType == StrategySignalType.MEAN_REVERSION_ENTRY ->
                ((marketSnapshot.tacticalBiasScore - 0.50) * 0.10).coerceIn(-0.03, 0.03)
            marketSnapshot.regime == MarketRegime.HIGH_VOLATILITY_MOMENTUM &&
                setupReadiness.signalType == StrategySignalType.BREAKOUT_ENTRY ->
                0.035
            else ->
                if (marketSnapshot.regime == MarketRegime.HEALTHY_UPTREND) 0.02 else 0.0
        }
        val followThroughScore = when (setupReadiness.setupType) {
            SetupType.SWING_TREND_CONTINUATION ->
                averageOf(pairScore.holdabilityScore, pairScore.trendQualityScore)
            SetupType.HEALTHY_SHORT_TERM_PULLBACK ->
                averageOf(pairScore.fillQualityScore, pairScore.spreadScore, pairScore.slippageScore)
            else ->
                averageOf(pairScore.trendQualityScore, pairScore.historicalExpectancyScore)
        }
        val dominanceBonus = if (dominantPairId == pairScore.pairId) 0.035 else 0.0
        val affordableUnits = if (quote.bestAsk.toDoubleOrZero() > 0.0) {
            targetBudgetIdr / quote.bestAsk.toDoubleOrZero()
        } else {
            0.0
        }
        val affordabilityScore = when {
            affordableUnits >= 2_500.0 -> 1.0
            affordableUnits >= 500.0 -> 0.88
            affordableUnits >= 100.0 -> 0.76
            affordableUnits >= 25.0 -> 0.64
            else -> 0.52
        }
        val learningBias = when {
            weeklySummary == null -> 0.0
            weeklySummary.falseEntryRate <= 0.18 -> 0.02
            weeklySummary.falseEntryRate >= 0.35 -> -0.04
            else -> 0.0
        }
        val leadLagBias = if (leadLagSignal != null && !leadLagSignal.fatigue) {
            (leadLagSignal.leadMomentumScore * 0.045)
        } else if (leadLagSignal?.fatigue == true) {
            -0.02
        } else {
            0.0
        }
        val aiBias = if (aiSoftAuditOnly) -0.015 else 0.0
        val urgentBias = if (urgentEntryMode) 0.04 else 0.0
        val speculativeBias = if (pairScore.speculativePocket) -0.03 else 0.0
        
        return weightedAverage(
            pairScore.rankingScore to 0.40,
            followThroughScore to 0.25,
            pairScore.marketOpportunityScore to 0.15,
            affordabilityScore to 0.10,
            modeSnapshot.edgeConfidence.toScore() to 0.10,
        ) + regimeBias + dominanceBonus + learningBias + leadLagBias + aiBias + urgentBias + speculativeBias
    }

    private fun buildSignalFromCandidate(
        candidate: CandidateSelection,
        marketSnapshot: MarketOpportunitySnapshot,
        modeSnapshot: BotModeSnapshot,
        dominantPairId: PairId?,
        productiveIdleBiasActive: Boolean,
        parallelMomentumBiasActive: Boolean,
        leadLagSignal: LeadLagSelectionSignal?,
        aiSoftAuditOnly: Boolean,
    ): StrategySignal {
        val selectedPairScore = candidate.pairScore
        val selectedQuote = candidate.quote
        val setupReadiness = candidate.setupReadiness
        val referencePrice = resolveEntryReferencePrice(
            quote = selectedQuote,
            pairScore = selectedPairScore,
            setupReadiness = setupReadiness,
        )
        val stopMultiplier = when {
            selectedPairScore.speculativePocket -> 0.978
            selectedPairScore.preferredHorizon == TradingHorizon.SWING -> 0.96
            else -> 0.985
        }
        val baseTakeProfitMultiplier = when {
            selectedPairScore.speculativePocket -> 1.03
            selectedPairScore.preferredHorizon == TradingHorizon.SWING -> 1.038
            setupReadiness.signalType == StrategySignalType.BREAKOUT_ENTRY -> 1.020
            else -> 1.016
        }
        val minimumTakeProfitMultiplier = 1.0 + ((1.0 - stopMultiplier) * 1.4)
        return StrategySignal(
            pairId = selectedPairScore.pairId,
            signalType = setupReadiness.signalType,
            confidence = candidate.selectionScore.coerceIn(0.0, 1.0),
            rationale = buildList {
                add("Pair ${selectedPairScore.pairId.value} masuk shortlist entry yang siap dieksekusi.")
                add(setupReadiness.rationale)
                if (aiSoftAuditOnly) {
                    add("AI sedang limited/offline, jadi keputusan entry tetap mengikuti sinyal teknikal dan momentum.")
                }
                if (dominantPairId == selectedPairScore.pairId) {
                    add("Kandidat ini unggul cukup jauh dari alternatif terdekat, jadi modal tidak dipaksa menyebar.")
                }
                if (selectedPairScore.speculativePocket) {
                    add("Trade ini masuk sleeve spekulatif, jadi eksposurnya dibatasi keras dan tidak boleh jadi posisi utama.")
                }
                if (productiveIdleBiasActive) {
                    add("Modal sedang idle, jadi threshold entry sedikit dilonggarkan pada kandidat yang benar-benar kuat.")
                }
                if (parallelMomentumBiasActive) {
                    add("Slot paralel momentum aktif: masih ada free cash dan shortlist sehat, jadi kandidat kedua boleh ditembak tanpa menunggu holding lama keluar.")
                }
                if (leadLagSignal?.fatigue == true) {
                    add(
                        if (aiSoftAuditOnly) {
                            "KiBot sedang soft-audit, jadi fatigue hanya jadi catatan dan bukan veto keras."
                        } else {
                            "KiBot mulai fatigue, jadi sinyal baru harus diperlakukan lebih ketat."
                        },
                    )
                }
            },
            entryPrice = referencePrice,
            takeProfitPrice = DecimalValue.fromDouble(
                referencePrice.toDoubleOrZero() * maxOf(baseTakeProfitMultiplier, minimumTakeProfitMultiplier),
            ),
            stopPrice = DecimalValue.fromDouble(
                referencePrice.toDoubleOrZero() * stopMultiplier,
            ),
            setupType = setupReadiness.setupType,
            horizon = selectedPairScore.preferredHorizon,
            pairTier = selectedPairScore.pairTier,
            speculativePocket = selectedPairScore.speculativePocket,
            marketRegime = marketSnapshot.regime,
            edgeConfidence = modeSnapshot.edgeConfidence,
            expectedHoldingHours = setupReadiness.expectedHoldingHours,
            expectedNetProfitabilityPct = selectedPairScore.feeAdjustedEdgeScore,
        )
    }

    fun buildExecutionPlans(
        signals: List<StrategySignal>,
        balances: List<BalanceSnapshot>,
        positions: List<PositionSnapshot>,
        quoteByPair: Map<PairId, MarketQuote>,
        marketQuotes: List<MarketQuote>,
        deploymentPlan: CapitalDeploymentPlan,
        modeSnapshot: BotModeSnapshot,
        rankedByPair: Map<PairId, PairScore>,
    ): List<ExecutionPlan> {
        return signals.mapNotNull { signal ->
            buildExecutionPlanFromSignal(
                signal = signal,
                balances = balances,
                positions = positions,
                quoteByPair = quoteByPair,
                marketQuotes = marketQuotes,
                deploymentPlan = deploymentPlan,
                modeSnapshot = modeSnapshot,
                rankedByPair = rankedByPair,
            )
        }
    }

    private fun buildExecutionPlanFromSignal(
        signal: StrategySignal,
        balances: List<BalanceSnapshot>,
        positions: List<PositionSnapshot>,
        quoteByPair: Map<PairId, MarketQuote>,
        marketQuotes: List<MarketQuote>,
        deploymentPlan: CapitalDeploymentPlan,
        modeSnapshot: BotModeSnapshot,
        rankedByPair: Map<PairId, PairScore>,
    ): ExecutionPlan? {
        val pairId = signal.pairId
        val quote = quoteByPair[pairId] ?: return null
        val pairScore = rankedByPair[pairId]
        val pairParts = pairId.assets()
        if (pairParts.quoteAsset !in executionConfig.executionAllowedQuoteAssets) return null
        
        val quoteAssetPriceIdr = quoteAssetReferencePrice(pairParts.quoteAsset, marketQuotes) ?: return null
        val quoteBalanceUnits = balances
            .firstOrNull { it.asset.equals(pairParts.quoteAsset, ignoreCase = true) }
            ?.free
            ?.toDoubleOrZero()
            ?: 0.0
        val availableQuoteBudgetIdr = quoteBalanceUnits * quoteAssetPriceIdr
        
        val rawBudgetIdr = minOf(
            maxOf(deploymentPlan.suggestedPerPositionBudgetIdr, executionConfig.minOrderNotionalIdr),
            availableQuoteBudgetIdr,
        )
        
        val rotationReserveBudgetIdr = if (
            deploymentPlan.allowRotation &&
            positions.any { it.state != PositionState.CLOSED }
        ) {
            maxOf(
                deploymentPlan.suggestedPerPositionBudgetIdr,
                positions
                    .filter { it.state != PositionState.CLOSED }
                    .minOfOrNull {
                        (
                            (it.quantity.toDoubleOrZero() * it.averageEntryPrice.toDoubleOrZero()) +
                                it.unrealizedPnlIdr.toDoubleOrZero()
                            ).coerceAtLeast(0.0)
                    }
                    ?: 0.0,
            )
        } else {
            0.0
        }
        
        val rotationFundingActive =
            deploymentPlan.allowRotation &&
                positions.any { it.state != PositionState.CLOSED } &&
                availableQuoteBudgetIdr < executionConfig.minOrderNotionalIdr
                
        val marketBuySignalEligible = pairParts.quoteAsset == executionConfig.referenceQuoteAsset &&
            signal.setupType == SetupType.LIGHT_BREAKOUT_CONTINUATION &&
            signal.confidence >= (if (signal.speculativePocket) {
                executionConfig.breakoutAggressiveEntryMinRankingScore
            } else {
                executionConfig.marketEntryMinRankingScore
            }) &&
            signal.expectedNetProfitabilityPct >= (if (signal.speculativePocket) {
                executionConfig.breakoutAggressiveEntryMinExpectedNetProfitPct
            } else {
                executionConfig.marketEntryMinExpectedNetProfitPct
            }) &&
            quote.spreadPct <= executionConfig.marketEntryMaxSpreadPct &&
            quote.estimatedSlippagePct <= executionConfig.marketEntryMaxSlippagePct &&
            quote.recentTradeActivityScore >= executionConfig.marketEntryMinTradeActivityScore &&
            quote.trendQualityScore >= executionConfig.marketEntryMinTrendScore &&
            quote.quoteVolume24h.toDoubleOrZero() >= 80_000_000.0 &&
            (pairScore?.rankingScore ?: 0.0) >= 0.58 &&
            signal.expectedNetProfitabilityPct >= maxOf(executionConfig.marketEntryMinExpectedNetProfitPct, 0.20) &&
            (signal.speculativePocket || modeSnapshot.mode in setOf(BotMode.GROWTH, BotMode.ATTACK))

        val effectiveRawBudgetIdr = if (rotationFundingActive) {
            maxOf(rawBudgetIdr, rotationReserveBudgetIdr)
        } else {
            minOf(
                maxOf(rawBudgetIdr, rotationReserveBudgetIdr),
                availableQuoteBudgetIdr,
            )
        }

        val portfolioCorrelationPenalty = derivePortfolioCorrelationPenalty(
            pairId = pairId,
            quote = quote,
            positions = positions,
            quoteByPair = quoteByPair,
        )
        if (portfolioCorrelationPenalty >= 0.80) return null

        val kellySizingMultiplier = pairScore?.kellyFraction
            ?.let { 0.38 + ((it / 0.35).coerceIn(0.0, 1.0) * 0.62) }
            ?: 0.58
        val toxicityBudgetPenalty = pairScore?.toxicityScore?.let { 1.0 - (it.coerceIn(0.0, 1.0) * 0.45) } ?: 1.0
        val portfolioDiversificationPenalty = 1.0 - (portfolioCorrelationPenalty * 0.55)
        
        val adjustedBudgetIdr = (effectiveRawBudgetIdr * kellySizingMultiplier * toxicityBudgetPenalty * portfolioDiversificationPenalty * (1.0 - executionConfig.entrySpendBufferPct))
            .coerceAtLeast(0.0)
            
        val bidDepthIdr = quote.bidDepthTop5Idr.toDoubleOrZero().coerceAtLeast(0.0)
        val liquidityImpactCapIdr = if (
            executionConfig.liquidityImpactReducerEnabled &&
            bidDepthIdr > 0.0
        ) {
            minOf(
                bidDepthIdr * executionConfig.liquidityImpactDepthCoverageRatio,
                bidDepthIdr * executionConfig.liquidityImpactMaxBudgetToBidDepthRatio,
            )
        } else {
            Double.POSITIVE_INFINITY
        }
        
        val budgetIdr = minOf(adjustedBudgetIdr, liquidityImpactCapIdr)
        if (budgetIdr < executionConfig.minOrderNotionalIdr && !marketBuySignalEligible) return null

        val projectedNetProfitIdr = budgetIdr * (signal.expectedNetProfitabilityPct / 100.0)

        val priceInQuoteAsset = signal.entryPrice.toDoubleOrZero().takeIf { it > 0.0 } ?: return null
        val budgetQuoteUnits = if (pairParts.quoteAsset == executionConfig.referenceQuoteAsset) {
            budgetIdr
        } else {
            budgetIdr / quoteAssetPriceIdr
        }
        
        val strongBreakoutMomentum = signal.setupType == SetupType.LIGHT_BREAKOUT_CONTINUATION &&
            quote.shortTermReturnPct >= 0.45 &&
            quote.recentTradeActivityScore >= 0.70

        val size = DecimalValue.fromDouble(budgetQuoteUnits / priceInQuoteAsset)
        
        return ExecutionPlan(
            signal = signal,
            side = OrderSide.BUY,
            type = if (marketBuySignalEligible) OrderType.MARKET else OrderType.LIMIT,
            price = signal.entryPrice,
            quantity = size,
            estimatedNotionalIdr = budgetIdr,
            rationale = buildList {
                add("Entry planned with budget IDR ${budgetIdr.toInt()} (${(kellySizingMultiplier * 100).toInt()}% Kelly).")
                if (rotationFundingActive) add("Rotation funding active: using reserve from potential exit.")
                if (portfolioCorrelationPenalty > 0.30) add("Diversification penalty applied due to ${(portfolioCorrelationPenalty * 100).toInt()}% correlation.")
                if (toxicityBudgetPenalty < 1.0) add("Toxicity penalty applied: ${(1.0 - toxicityBudgetPenalty) * 100}% reduction.")
                if (liquidityImpactCapIdr < adjustedBudgetIdr) add("Liquidity impact cap restricted size to depth coverage.")
                if (marketBuySignalEligible) add("Strong momentum & liquidity detected: using MARKET entry for immediate fill.")
            },
            projectedNetProfitIdr = projectedNetProfitIdr,
        )
    }

    private fun derivePortfolioCorrelationPenalty(
        pairId: PairId,
        quote: MarketQuote,
        positions: List<PositionSnapshot>,
        quoteByPair: Map<PairId, MarketQuote>,
    ): Double {
        val openPositions = positions.filter { it.state != PositionState.CLOSED && it.pairId != pairId }
        if (openPositions.isEmpty()) return 0.0
        val candidateFamily = correlationFamilyOf(pairId)
        return openPositions.maxOf { position ->
            val heldQuote = quoteByPair[position.pairId]
            val sameFamily = candidateFamily == correlationFamilyOf(position.pairId)
            val familyAffinity = if (sameFamily) 1.0 else 0.0
            val sectorAffinity = if (sameFamily) 0.88 else averageOf(
                quote.sectorMomentumScore.coerceIn(0.0, 1.0),
                heldQuote?.sectorMomentumScore?.coerceIn(0.0, 1.0) ?: 0.5,
            )
            val betaAffinity = averageOf(
                quote.globalCorrelationScore.coerceIn(0.0, 1.0),
                heldQuote?.globalCorrelationScore?.coerceIn(0.0, 1.0) ?: 0.5,
            )
            val returnAlignment = heldQuote?.let {
                val shortAlignment = 1.0 - kotlin.math.abs(quote.shortTermReturnPct - it.shortTermReturnPct).coerceAtMost(6.0) / 6.0
                val mediumAlignment = 1.0 - kotlin.math.abs(quote.mediumTermReturnPct - it.mediumTermReturnPct).coerceAtMost(8.0) / 8.0
                averageOf(shortAlignment, mediumAlignment).coerceIn(0.0, 1.0)
            } ?: 0.45
            val assetOverlap = if (pairId.value.substringBefore('_').equals(position.pairId.value.substringBefore('_'), ignoreCase = true)) 1.0 else 0.0
            weightedAverage(
                assetOverlap to 0.10,
                familyAffinity to 0.50,
                sectorAffinity to 0.15,
                betaAffinity to 0.15,
                returnAlignment to 0.10,
            )
        }.coerceIn(0.0, 1.0)
    }

    private fun quoteAssetReferencePrice(asset: String, marketQuotes: List<MarketQuote>): Double? {
        val normalizedAsset = asset.lowercase()
        val referenceQuoteAsset = executionConfig.referenceQuoteAsset.lowercase()
        if (normalizedAsset == referenceQuoteAsset) return 1.0

        val directPair = "${normalizedAsset}_${referenceQuoteAsset}"
        marketQuotes.firstOrNull { it.pairId.value.equals(directPair, ignoreCase = true) }
            ?.midPrice
            ?.toDoubleOrZero()
            ?.takeIf { it > 0.0 }
            ?.let { return it }

        if (referenceQuoteAsset != "idr") {
            marketQuotes.firstOrNull { it.pairId.value.equals("${normalizedAsset}_idr", ignoreCase = true) }
                ?.midPrice
                ?.toDoubleOrZero()
                ?.takeIf { it > 0.0 }
                ?.let { directIdr ->
                    val referenceIdr = marketQuotes.firstOrNull {
                        it.pairId.value.equals("${referenceQuoteAsset}_idr", ignoreCase = true)
                    }?.midPrice?.toDoubleOrZero() ?: return null
                    return directIdr / referenceIdr
                }
        }
        return null
    }

    private fun hasFundedQuoteAsset(
        pairId: PairId,
        balances: List<BalanceSnapshot>,
        marketQuotes: List<MarketQuote>,
        targetBudgetIdr: Double,
    ): Boolean {
        val quoteAsset = pairId.assets().quoteAsset
        val balance = balances.firstOrNull { it.asset.equals(quoteAsset, ignoreCase = true) } ?: return false
        val freeUnits = balance.free.toDoubleOrZero()
        if (freeUnits <= 0.0) return false
        val referencePrice = quoteAssetReferencePrice(quoteAsset, marketQuotes) ?: return false
        return (freeUnits * referencePrice) >= (targetBudgetIdr * 0.95)
    }

    private fun speculativePocketAllowed(marketSnapshot: MarketOpportunitySnapshot): Boolean {
        return marketSnapshot.regime in setOf(MarketRegime.HEALTHY_UPTREND, MarketRegime.HEALTHY_SIDEWAYS) &&
            marketSnapshot.edgeConfidence != EdgeConfidence.LOW &&
            marketSnapshot.botHealthScore >= 0.62
    }

    private fun resolveEntryReferencePrice(
        quote: MarketQuote,
        pairScore: PairScore,
        setupReadiness: SetupReadiness,
    ): DecimalValue {
        return when {
            pairScore.speculativePocket || setupReadiness.signalType == StrategySignalType.BREAKOUT_ENTRY ->
                quote.bestAsk.takeIf { it.toDoubleOrZero() > 0.0 } ?: quote.bestBid
            else -> quote.bestBid
        }
    }


}

private data class EntryThresholds(
    val minRankingScore: Double,
    val minOpportunityScore: Double,
    val productiveIdleBiasActive: Boolean,
    val parallelMomentumBiasActive: Boolean,
    val dailyProfitLockActive: Boolean,
)

private data class SetupReadiness(
    val setupType: SetupType,
    val signalType: StrategySignalType,
    val expectedHoldingHours: Double,
    val rationale: String,
)

private data class CandidateSelection(
    val pairScore: PairScore,
    val quote: MarketQuote,
    val setupReadiness: SetupReadiness,
    val selectionScore: Double,
)

private data class PairParts(
    val baseAsset: String,
    val quoteAsset: String,
)

private fun PairId.assets(): PairParts {
    val parts = value.lowercase().split("_")
    return if (parts.size == 2) {
        PairParts(parts[0], parts[1])
    } else {
        val quote = listOf("idr", "usdt", "btc", "eth").firstOrNull { value.lowercase().endsWith(it) }
            ?: error("Unsupported pair format: ${value}")
        PairParts(value.lowercase().removeSuffix(quote), quote)
    }
}

private val activeBuyOrderStatuses = setOf(
    OrderStatus.CREATED,
    OrderStatus.SUBMITTING,
    OrderStatus.OPEN,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.CANCEL_REQUESTED,
    OrderStatus.UNKNOWN,
)
