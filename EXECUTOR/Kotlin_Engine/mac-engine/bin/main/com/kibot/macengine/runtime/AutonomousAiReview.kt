package com.kibot.macengine.runtime

import com.kibot.core.ManagedPosition
import com.kibot.core.TradeRecord
import com.kibot.shared.models.AiPairSupportHint
import com.kibot.shared.models.MarketRegime
import com.kibot.shared.models.PairId
import kotlinx.datetime.Instant
import kotlinx.serialization.Serializable

@Serializable
data class AutonomousAiSummaryFile(
    val successful_providers: List<String> = emptyList(),
    val failed_providers: List<String> = emptyList(),
    val skipped_providers: Map<String, String> = emptyMap(),
    val errors: Map<String, String> = emptyMap(),
    val adaptive_policy_path: String? = null,
)

data class AutonomousAiReviewInput(
    val now: Instant,
    val botId: String,
    val topCandidate: PairId?,
    val marketRegime: MarketRegime,
    val freeIdr: Double,
    val dailyPnlPct: Double,
    val holdings: List<ManagedPosition>,
    val aiHints: List<AiPairSupportHint>,
    val aiUsedNetwork: Boolean,
    val aiBlockedReason: String?,
    val recentTrades: List<TradeRecord>,
    val learningSnapshot: LocalLearningSnapshot? = null,
)

data class AutonomousAiReviewOutput(
    val policy: AdaptiveAiPolicyFile,
    val summary: AutonomousAiSummaryFile,
    val runtimeLabel: String,
)

object AutonomousAiReviewBuilder {
    fun build(
        input: AutonomousAiReviewInput,
        adaptivePolicyPath: String,
    ): AutonomousAiReviewOutput {
        val recentTrades = input.recentTrades.takeLast(18)
        val learningSnapshot = input.learningSnapshot
        val wins = recentTrades.count { it.netProfitIdr > 0.0 }
        val losses = recentTrades.count { it.netProfitIdr < 0.0 }
        val averageTradePnlPct = recentTrades.map { it.netProfitPct }.let { profits ->
            if (profits.isEmpty()) 0.0 else profits.average().let { if (it.isNaN()) 0.0 else it }
        }
        val recentTradeFeesIdr = recentTrades.sumOf { it.totalFeeIdr }
        val recentTradeProfitIdr = recentTrades.sumOf { it.netProfitIdr }
        val badPairs = recentTrades
            .groupBy { it.pair.lowercase() }
            .filterValues { trades ->
                trades.size >= 2 && trades.count { it.netProfitIdr < 0.0 } >= trades.count { it.netProfitIdr > 0.0 }
            }
            .keys
            .map { it.substringBefore('_') }
            .take(4)

        val losingHoldings = input.holdings.filter { it.unrealizedPnlPct <= -1.35 }
        val staleHoldings = input.holdings.filter { holding ->
            val ageHours = ((input.now.toEpochMilliseconds() - holding.openedAt.toEpochMilliseconds()).coerceAtLeast(0L) / 3_600_000.0)
            ageHours >= 4.0 && holding.unrealizedPnlPct < 0.8
        }
        val winningHoldings = input.holdings.filter { it.unrealizedPnlPct >= 1.20 }
        val strongWinners = input.holdings.filter { it.unrealizedPnlPct >= 2.20 }

        val successfulProviders = when {
            input.aiUsedNetwork -> listOf("gemini")
            input.aiHints.isNotEmpty() -> listOf("gemini_cached")
            else -> emptyList()
        }
        val skippedProviders = buildMap<String, String> {
            input.aiBlockedReason
                ?.trim()
                ?.takeIf { it.isNotBlank() }
                ?.let { put("gemini", it.replace(' ', '_')) }
        }
        val consensusStrength = when {
            successfulProviders.isEmpty() && input.aiHints.isEmpty() -> 0.0
            input.aiUsedNetwork && input.aiHints.isNotEmpty() -> 0.82
            input.aiUsedNetwork -> 0.64
            else -> 0.46
        }

        val focusPairs = buildList {
            input.topCandidate?.value?.lowercase()?.let(::add)
            addAll(input.aiHints.map { it.pairId.value.lowercase() })
            addAll(input.holdings.map { it.pairId.value.lowercase() })
        }.distinct().take(8)

        val pairBiases = input.aiHints
            .groupBy { it.pairId }
            .map { (pairId, hints) ->
                val latest = hints.maxByOrNull { it.generatedAt.toEpochMilliseconds() } ?: hints.first()
                AdaptiveAiPairBias(
                    pairId = pairId.value.lowercase(),
                    supportBias = hints.maxOf { it.supportBias }.coerceIn(0.0, 0.08),
                    cautionBias = hints.maxOf { it.cautionBias }.coerceIn(0.0, 0.06),
                    rationale = latest.rationale.ifBlank { "AI runtime review" },
                )
            }
            .toMutableList()

        learningSnapshot?.pairTrustScores
            ?.entries
            ?.sortedBy { it.value }
            ?.take(8)
            ?.forEach { (pairId, trust) ->
                val normalizedPair = pairId.lowercase()
                val existingIndex = pairBiases.indexOfFirst { it.pairId.equals(normalizedPair, ignoreCase = true) }
                val supportBias = when {
                    trust >= 0.72 -> 0.03
                    trust >= 0.62 -> 0.015
                    else -> 0.0
                }
                val cautionBias = when {
                    trust <= 0.32 -> 0.06
                    trust <= 0.45 -> 0.04
                    trust <= 0.55 -> 0.02
                    else -> 0.0
                }
                if (supportBias <= 0.0 && cautionBias <= 0.0) return@forEach
                val rationale = if (cautionBias > 0.0) {
                    "Local learning trust score rendah (${String.format("%.2f", trust)})."
                } else {
                    "Local learning trust score tinggi (${String.format("%.2f", trust)})."
                }
                if (existingIndex >= 0) {
                    val existing = pairBiases[existingIndex]
                    pairBiases[existingIndex] = existing.copy(
                        supportBias = maxOf(existing.supportBias, supportBias),
                        cautionBias = maxOf(existing.cautionBias, cautionBias),
                        rationale = listOf(existing.rationale, rationale).filter { it.isNotBlank() }.joinToString(" | ").take(240),
                    )
                } else {
                    pairBiases += AdaptiveAiPairBias(
                        pairId = normalizedPair,
                        supportBias = supportBias,
                        cautionBias = cautionBias,
                        rationale = rationale,
                    )
                }
            }

        val rotateNowPairs = ((losingHoldings + staleHoldings)
            .map { it.pairId.value.lowercase() }
            .distinct() + learningSnapshot?.rotateNowPairs.orEmpty())
            .distinct()
            .take(5)
        val holdLongerPairs = (winningHoldings
            .sortedByDescending { it.unrealizedPnlPct }
            .map { it.pairId.value.lowercase() }
            .distinct() + learningSnapshot?.holdLongerPairs.orEmpty())
            .distinct()
            .take(4)

        val concentrationPair = input.topCandidate
            ?.takeIf {
                input.freeIdr >= 20_000.0 &&
                    input.marketRegime == MarketRegime.HIGH_VOLATILITY_MOMENTUM &&
                    strongWinners.size <= 2 &&
                    input.dailyPnlPct > -2.5
            }
            ?.value
            ?.lowercase()

        val redDay = input.dailyPnlPct < 0.0
        val severeRedDay = input.dailyPnlPct <= -2.5
        val criticalRedDay = input.dailyPnlPct <= -4.0
        val cautiousDay = losses > wins || averageTradePnlPct < 0.0 || redDay
        val risk = learningSnapshot?.risk ?: LearningRiskSnapshot()
        val lossRecoveryMode = severeRedDay ||
            recentTradeProfitIdr < 0.0 ||
            (losses >= wins && losses >= 2) ||
            risk.ruinProbability >= 0.28 ||
            risk.bootstrapConditionalVar95Pct <= -3.2 ||
            risk.maxDrawdownPct >= 5.0
        val missedMomentumWindow = input.marketRegime == MarketRegime.HIGH_VOLATILITY_MOMENTUM &&
            input.freeIdr >= 20_000.0 &&
            input.topCandidate != null
        val hourlyAggressionMultiplier = learningSnapshot?.hourlyAggressionMultiplier ?: 1.0
        val dailyAggressionBias = learningSnapshot?.dailyAggressionBias ?: 0.0
        val riskPressure = when {
            risk.ruinProbability >= 0.35 || risk.bootstrapConditionalVar95Pct <= -4.0 -> 0.18
            risk.ruinProbability >= 0.25 || risk.bootstrapConditionalVar95Pct <= -3.0 -> 0.10
            risk.sortinoLikeRatio < -0.20 -> 0.08
            else -> 0.0
        }
        val learningBudgetDelta = ((hourlyAggressionMultiplier - 1.0) + dailyAggressionBias - riskPressure).coerceIn(-0.30, 0.20)
        val learningReserveDelta = when {
            risk.ruinProbability >= 0.35 -> -0.035
            risk.bootstrapConditionalVar95Pct <= -3.5 -> -0.025
            learningBudgetDelta <= -0.18 -> -0.030
            learningBudgetDelta <= -0.08 -> -0.018
            learningBudgetDelta >= 0.10 -> 0.012
            learningBudgetDelta >= 0.05 -> 0.006
            else -> 0.0
        }
        val learningExtraSlots = when {
            risk.ruinProbability >= 0.28 -> -1
            learningBudgetDelta <= -0.18 -> -1
            learningBudgetDelta >= 0.12 && input.freeIdr >= 60_000.0 -> 1
            else -> 0
        }
        val learningTemporaryBlacklist = learningSnapshot?.temporaryBlacklistPairs.orEmpty().take(5)
        val learningForceLimitPairs = learningSnapshot?.forceLimitPairs.orEmpty().take(4)
        val learningForceMarketPairs = learningSnapshot?.forceMarketPairs.orEmpty().take(4)
        val learningTightTrailingPairs = learningSnapshot?.tightenTrailingPairs.orEmpty().take(5)
        val learningNotes = learningSnapshot?.notes.orEmpty().take(6)
        val recoveryBlacklistPairs = if (lossRecoveryMode) {
            (rotateNowPairs + badPairs.map { "${it}_idr" }).distinct().take(5)
        } else {
            emptyList()
        }
        val recoveryForceLimitPairs = if (lossRecoveryMode) {
            (learningForceLimitPairs + focusPairs.take(3)).distinct().take(6)
        } else {
            learningForceLimitPairs
        }
        val recoveryTightTrailingPairs = if (redDay) {
            (learningTightTrailingPairs + winningHoldings.map { it.pairId.value.lowercase() }).distinct().take(6)
        } else {
            learningTightTrailingPairs
        }

        val policy = AdaptiveAiPolicyFile(
            generatedAtUtc = input.now.toString(),
            policyTtlMinutes = 35,
            successfulProviders = successfulProviders,
            consensusStrength = consensusStrength,
            focusPairs = focusPairs,
            pairBiases = pairBiases.take(8),
            adjustments = AdaptiveAiAdjustments(
                rankingBiasScale = (1.0 + (consensusStrength * 0.24)).coerceIn(1.0, 1.32),
                rotationAgeHoursDelta = when {
                    losingHoldings.isNotEmpty() || staleHoldings.isNotEmpty() -> -0.35
                    cautiousDay -> -0.18
                    else -> -0.08
                },
                rotationScoreGapDelta = if (cautiousDay) -0.02 else 0.0,
                partialTakeProfitPnlDelta = when {
                    severeRedDay -> -0.75
                    redDay -> -0.45
                    strongWinners.isNotEmpty() -> -0.25
                    else -> -0.12
                },
                winnerRunPnlDelta = when {
                    strongWinners.isNotEmpty() && !redDay -> 0.14
                    winningHoldings.isNotEmpty() -> 0.08
                    else -> 0.0
                },
                meaningfulExitProfitDelta = when {
                    severeRedDay -> -0.18
                    redDay -> -0.10
                    else -> -0.04
                },
                budgetBoostMultiplierDelta = when {
                    criticalRedDay -> -0.20
                    severeRedDay -> -0.14
                    risk.sharpeLikeRatio >= 0.22 && risk.sortinoLikeRatio >= 0.20 && risk.skewness > 0.0 && !redDay -> 0.06
                    risk.ruinProbability >= 0.30 -> -0.12
                    risk.bootstrapConditionalVar95Pct <= -3.2 -> -0.08
                    missedMomentumWindow && !redDay -> 0.12
                    missedMomentumWindow -> 0.06
                    else -> 0.0
                } + learningBudgetDelta,
                reserveReliefPctDelta = when {
                    criticalRedDay -> -0.045
                    severeRedDay -> -0.030
                    redDay -> -0.015
                    missedMomentumWindow && !redDay -> 0.015
                    else -> 0.0
                } + learningReserveDelta,
                allocationFocusPctDelta = when {
                    concentrationPair != null -> 0.035
                    else -> 0.0
                },
                extraSlotsDelta = when {
                    criticalRedDay -> -2
                    severeRedDay -> -1
                    input.freeIdr >= 200_000.0 -> 2
                    input.freeIdr >= 40_000.0 -> 1
                    else -> 0
                } + learningExtraSlots,
            ),
            execution = AdaptiveAiExecutionFile(
                rotateNowPairs = rotateNowPairs,
                holdLongerPairs = holdLongerPairs,
                temporaryBlacklistPairs = (learningTemporaryBlacklist + recoveryBlacklistPairs).distinct().take(6),
                forceLimitPairs = if (severeRedDay) {
                    (recoveryForceLimitPairs + focusPairs.take(4)).distinct().take(8)
                } else {
                    recoveryForceLimitPairs
                },
                forceMarketPairs = if (severeRedDay) emptyList() else learningForceMarketPairs,
                tightTrailingPairs = recoveryTightTrailingPairs,
                concentrationPair = concentrationPair,
                avoidPairFamilies = badPairs,
                replacementHints = rotateNowPairs.zip(focusPairs.filterNot { it in rotateNowPairs }).take(2).map { (cutPair, replacePair) ->
                    AdaptiveAiReplacementFile(
                        cutPair = cutPair,
                        replacePair = replacePair,
                        rationale = "Autonomous runtime review mendeteksi pair lama lebih lemah daripada fokus pair saat ini.",
                    )
                },
                learningNotes = learningNotes,
            ),
            watchdog = AdaptiveAiWatchdogFile(
                status = when {
                    severeRedDay -> "PRESSURED"
                    cautiousDay -> "WATCH"
                    else -> "IDLE"
                },
                severity = when {
                    severeRedDay -> "HIGH"
                    cautiousDay -> "MEDIUM"
                    else -> "LOW"
                },
                reprimand = when {
                    severeRedDay -> "Pakai profit lock lebih cepat, prioritaskan winner yang likuid, dan buang loser yang terus menyedot modal."
                    cautiousDay -> "Kurangi pair yang lemah, hormati break-even lebih cepat, dan prioritaskan fokus ke kandidat paling sehat."
                    else -> "Runtime adaptive review sehat."
                },
                rootCauses = buildList {
                    if (criticalRedDay) add("critical_red_day")
                    if (severeRedDay || redDay) add("daily_pnl_red")
                    if (losses > wins) add("recent_loss_cluster")
                    if (risk.historicalVar95Pct < 0.0) add("historical_var95_${"%.2f".format(risk.historicalVar95Pct)}pct")
                    if (risk.bootstrapConditionalVar95Pct < 0.0) add("bootstrap_cvar95_${"%.2f".format(risk.bootstrapConditionalVar95Pct)}pct")
                    if (risk.maxDrawdownPct > 0.0) add("max_drawdown_${"%.2f".format(risk.maxDrawdownPct)}pct")
                    if (risk.ruinProbability >= 0.20) add("ruin_probability_${"%.2f".format(risk.ruinProbability)}")
                    if (risk.sortinoLikeRatio < 0.0) add("negative_sortino_${"%.2f".format(risk.sortinoLikeRatio)}")
                    if (risk.kurtosis >= 3.0) add("fat_tail_kurtosis_${"%.2f".format(risk.kurtosis)}")
                    if (recentTradeFeesIdr > kotlin.math.abs(recentTradeProfitIdr) * 0.45 && recentTradeFeesIdr > 0.0) add("fee_drag_detected")
                    if (losingHoldings.isNotEmpty()) add("losing_holdings_present")
                    if (missedMomentumWindow) add("unused_free_cash_in_momentum")
                    if (learningTemporaryBlacklist.isNotEmpty() || recoveryBlacklistPairs.isNotEmpty()) add("local_learning_blacklist_active")
                    if (learningForceLimitPairs.isNotEmpty() || recoveryForceLimitPairs.isNotEmpty()) add("slippage_or_spoofing_detected")
                    if (lossRecoveryMode) add("loss_recovery_mode")
                },
                requiredActions = buildList {
                    if (criticalRedDay) add("aktifkan Red Day Protocol level-3: freeze market-order agresif dan fokus recovery defensif")
                    if (severeRedDay || redDay) add("profit lock lebih cepat pada posisi yang sudah cover fee")
                    if (risk.bootstrapConditionalVar95Pct <= -3.0) add("tail risk tinggi; kecilkan sleeve agresif dan paksa limit-first kecuali lead-lag sangat kuat")
                    if (risk.maxDrawdownPct >= 5.0) add("drawdown tinggi; rotasi lebih cepat dari pair yang stagnan atau manipulatif")
                    if (risk.sortinoLikeRatio < 0.0) add("downside risk lebih dominan dari upside; fokus hanya pada pair dengan trust score tinggi")
                    if (risk.sharpeLikeRatio >= 0.22 && risk.skewness > 0.0 && !redDay) add("reward per risiko sedang sehat; izinkan winner run sedikit lebih lama")
                    if (losingHoldings.isNotEmpty()) add("rotasi loser ke pair fokus yang lebih sehat")
                    if (missedMomentumWindow) add("izinkan slot taktis tambahan untuk pair fokus")
                    if (recentTradeFeesIdr > 0.0) add("utamakan limit order untuk sleeve stabil")
                    if (learningForceMarketPairs.isNotEmpty()) add("izinkan market order taktis hanya pada pair lead-lag yang delay-nya terbukti lambat")
                    if (learningTightTrailingPairs.isNotEmpty() || recoveryTightTrailingPairs.isNotEmpty()) add("ketatkan trailing stop pada pair fake pump / peak decay")
                    if (lossRecoveryMode) add("aktifkan mode pemulihan rugi: fokus likuiditas, limit-first, dan blacklist pair yang berulang kali gagal")
                },
                forceRotation = losingHoldings.isNotEmpty() || staleHoldings.isNotEmpty(),
                forceConcentration = concentrationPair != null && !redDay,
                pressureFloor = when {
                    criticalRedDay -> 0.85
                    severeRedDay -> 0.72
                    cautiousDay -> 0.48
                    else -> 0.18
                },
                budgetBoostFloor = when {
                    criticalRedDay -> 0.70
                    missedMomentumWindow && !redDay -> 1.10
                    learningBudgetDelta <= -0.18 -> 0.78
                    learningBudgetDelta <= -0.08 -> 0.88
                    else -> 1.0
                },
                executionBoostFloor = when {
                    missedMomentumWindow -> 1.08
                    else -> 1.0
                },
                reserveReliefFloor = when {
                    concentrationPair != null && !redDay -> 0.015
                    else -> 0.0
                },
            ),
        )

        val runtimeLabel = when {
            input.aiUsedNetwork -> "AI ONLINE (30m adaptive review)"
            input.aiHints.isNotEmpty() -> "AI ONLINE (cached adaptive review)"
            input.aiBlockedReason != null -> "AI LIMITED (${input.aiBlockedReason.replace('_', ' ')})"
            else -> "AI ONLINE (heuristic adaptive review)"
        }

        return AutonomousAiReviewOutput(
            policy = policy,
            summary = AutonomousAiSummaryFile(
                successful_providers = successfulProviders,
                skipped_providers = skippedProviders,
                adaptive_policy_path = adaptivePolicyPath,
            ),
            runtimeLabel = runtimeLabel,
        )
    }
}
