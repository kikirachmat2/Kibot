package com.kibot.macengine.runtime

import com.kibot.core.StrategyCycleResult
import com.kibot.shared.models.DecimalValue
import kotlinx.datetime.Instant
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max

data class DailyTargetPursuitConfig(
    val targetProfitPct: Double = 25.0,
    val dailyLossLimitPct: Double = 2.0,
    val hourlyEvaluationCadenceHours: Double = 1.0,
    val threeHourCheckpointPct: Double = 10.0,
    val checkpointCadenceHours: Double = 3.0,
    val warmupHours: Double = 1.5,
    val hourlyUnrealizedCreditWeight: Double = 0.06,
    val checkpointUnrealizedCreditWeight: Double = 0.05,
    val targetSatisfiedUnrealizedCreditWeight: Double = 0.03,
    val minUnrealizedCreditWeight: Double = 0.14,
    val maxUnrealizedCreditWeight: Double = 0.36,
    val maxBudgetBoostMultiplier: Double = 1.60,
    val maxReserveReliefPct: Double = 0.08,
    val maxExtraSlots: Int = 1,
    val maxExecutionBoostMultiplier: Double = 1.42,
    val maxConcentrationBoostPct: Double = 0.16,
    val minEquityForExtraSlotIdr: Double = 125_000.0,
)

data class DailyTargetPursuit(
    val phase: String,
    val currentProfitPct: Double,
    val progressPct: Double,
    val targetGapPct: Double,
    val urgency: Double,
    val hourlyWindowIndex: Int,
    val hourlyMissed: Boolean,
    val hourlyMissCount: Int,
    val hourlyShortfallPct: Double,
    val hourlyEscalationLevel: Int,
    val checkpointWindowIndex: Int,
    val checkpointMissed: Boolean,
    val checkpointShortfallPct: Double,
    val checkpointEscalationLevel: Int,
    val forcedReplan: Boolean,
    val profitWindowOpen: Boolean,
    val targetSatisfied: Boolean,
    val overdriveAllowed: Boolean,
    val budgetBoostMultiplier: Double,
    val reserveReliefPct: Double,
    val executionBoostMultiplier: Double,
    val extraSlots: Int,
    val concentrationBoostPct: Double,
    val rotationAgeHoursDelta: Double,
    val rotationScoreGapDelta: Double,
    val partialTakeProfitPnlDelta: Double,
    val winnerRunPnlDelta: Double,
    val meaningfulExitProfitDelta: Double,
    val rationale: List<String>,
) {
    val active: Boolean = urgency > 0.05
}

class DailyTargetPursuitBrain(
    private val config: DailyTargetPursuitConfig = DailyTargetPursuitConfig(),
) {
    fun evaluate(
        cycle: StrategyCycleResult,
        adaptiveAiPolicy: AdaptiveAiPolicy?,
        now: Instant,
        timeZone: TimeZone = TimeZone.of("Asia/Jakarta"),
    ): DailyTargetPursuit {
        val openingEquity = cycle.dailyRisk.openingEquityIdr.toDoubleOrZero().takeIf { it > 0.0 }
            ?: cycle.portfolio.totalEquityIdr.toDoubleOrZero().coerceAtLeast(1.0)
        val currentEquity = cycle.portfolio.totalEquityIdr.toDoubleOrZero().coerceAtLeast(0.0)
        val localDateTime = now.toLocalDateTime(timeZone)
        val elapsedHours = localDateTime.hour + (localDateTime.minute / 60.0)
        val realizedProfitPct = if (openingEquity > 0.0) {
            (cycle.dailyRisk.realizedPnlIdr.toDoubleOrZero() / openingEquity) * 100.0
        } else {
            0.0
        }
        val unrealizedProfitPct = if (openingEquity > 0.0) {
            (cycle.dailyRisk.unrealizedPnlIdr.toDoubleOrZero() / openingEquity) * 100.0
        } else {
            0.0
        }
        val unrealizedCreditWeight = (
            config.minUnrealizedCreditWeight +
                (((elapsedHours / 24.0).coerceIn(0.0, 1.0)) * (config.maxUnrealizedCreditWeight - config.minUnrealizedCreditWeight))
            ).coerceIn(config.minUnrealizedCreditWeight, config.maxUnrealizedCreditWeight)
        val effectiveProfitPct = realizedProfitPct + (unrealizedProfitPct * unrealizedCreditWeight)
        val controllerProfitPct = realizedProfitPct + (unrealizedProfitPct * config.hourlyUnrealizedCreditWeight)
        val checkpointProfitPct = realizedProfitPct + (unrealizedProfitPct * config.checkpointUnrealizedCreditWeight)
        val targetSatisfiedProfitPct = realizedProfitPct + (unrealizedProfitPct * config.targetSatisfiedUnrealizedCreditWeight)
        val progressPct = (controllerProfitPct / config.targetProfitPct).coerceIn(-1.0, 2.5)
        val targetGapPct = (config.targetProfitPct - controllerProfitPct).coerceAtLeast(0.0)
        val normalizedDayProgress = ((elapsedHours - config.warmupHours) / max(1.0, 24.0 - config.warmupHours))
            .coerceIn(0.0, 1.0)
        val normalizedTargetProgress = (controllerProfitPct / config.targetProfitPct).coerceIn(0.0, 1.0)
        val behindSchedule = (normalizedDayProgress - normalizedTargetProgress).coerceAtLeast(0.0)
        val gapPressure = (targetGapPct / config.targetProfitPct).coerceIn(0.0, 1.35)
        val drawdownPenalty = cycle.dailyRisk.drawdownPct.coerceIn(0.0, 0.18)
        val aiConsensus = adaptiveAiPolicy?.consensusStrength?.coerceIn(0.0, 1.0) ?: 0.0
        val hourlyEvaluationWindow = kotlin.math.floor(elapsedHours / config.hourlyEvaluationCadenceHours)
            .toInt()
            .coerceAtLeast(0)
        val expectedProfitByNowPct = expectedProfitAt(elapsedHours)
        val hourlyExpectedProfitPct = if (hourlyEvaluationWindow > 0) {
            expectedProfitAt(hourlyEvaluationWindow * config.hourlyEvaluationCadenceHours)
        } else {
            0.0
        }
        val completedCheckpointWindow = kotlin.math.floor(elapsedHours / config.checkpointCadenceHours)
            .toInt()
            .coerceAtLeast(0)
        val checkpointExpectedProfitPct = if (completedCheckpointWindow > 0) {
            checkpointTargetAtWindow(completedCheckpointWindow)
        } else {
            0.0
        }
        val checkpointShortfallPct = (checkpointExpectedProfitPct - checkpointProfitPct).coerceAtLeast(0.0)
        val checkpointMissed = completedCheckpointWindow > 0 && checkpointShortfallPct > 0.0
        val hourlyShortfallPct = (hourlyExpectedProfitPct - controllerProfitPct).coerceAtLeast(0.0)
        val hourlyMissed = hourlyEvaluationWindow > 0 && hourlyShortfallPct > 0.0
        val targetPctPerHour = (config.targetProfitPct / 24.0).coerceAtLeast(0.10)
        val hourlyMissCount = if (hourlyMissed) {
            ceil(hourlyShortfallPct / targetPctPerHour).toInt().coerceIn(1, 6)
        } else {
            0
        }
        val hourlyEscalationLevel = when {
            !hourlyMissed -> 0
            hourlyShortfallPct >= 3.2 || hourlyMissCount >= 3 -> 3
            hourlyShortfallPct >= 1.6 || hourlyMissCount >= 2 -> 2
            else -> 1
        }
        val checkpointEscalationLevel = when {
            !checkpointMissed -> 0
            completedCheckpointWindow >= 3 || checkpointShortfallPct >= 6.0 -> 3
            completedCheckpointWindow >= 2 || checkpointShortfallPct >= 3.0 -> 2
            else -> 1
        }
        val forcedReplan = checkpointMissed ||
            hourlyMissCount >= 2 ||
            (hourlyMissed && elapsedHours >= 1.5 && hourlyShortfallPct >= 0.90)
        val topCandidateQuality = cycle.deploymentPlan.candidates.firstOrNull()?.let {
            (it.rankingScore * 0.58) + (it.marketOpportunityScore * 0.42)
        } ?: 0.0
        val strongBenchCount = cycle.deploymentPlan.candidates.count {
            it.rankingScore >= 0.72 &&
                it.marketOpportunityScore >= 0.66 &&
                it.expectedNetProfitabilityPct >= 1.20
        }
        val explosiveBenchCount = cycle.deploymentPlan.candidates.count {
            it.rankingScore >= 0.82 &&
                it.marketOpportunityScore >= 0.74 &&
                it.expectedNetProfitabilityPct >= 2.10
        }
        val profitWindowOpen =
            topCandidateQuality >= 0.80 ||
                explosiveBenchCount >= 1 ||
                strongBenchCount >= 2 ||
                aiConsensus >= 0.68 ||
                cycle.selectedSignal?.expectedNetProfitabilityPct?.let { it >= 2.8 } == true
        val targetSatisfied = (
            realizedProfitPct >= (config.targetProfitPct * 0.82) ||
                (
                    targetSatisfiedProfitPct >= config.targetProfitPct &&
                        realizedProfitPct >= (config.targetProfitPct * 0.60)
                    )
            ) &&
            cycle.dailyRisk.givebackPct <= 0.10
        val dailyLossBreached = controllerProfitPct <= -abs(config.dailyLossLimitPct)
        if (dailyLossBreached) {
            return DailyTargetPursuit(
                phase = "HARD_STOPPED",
                currentProfitPct = effectiveProfitPct,
                progressPct = progressPct,
                targetGapPct = targetGapPct,
                urgency = 0.0,
                hourlyWindowIndex = hourlyEvaluationWindow,
                hourlyMissed = hourlyMissed,
                hourlyMissCount = hourlyMissCount,
                hourlyShortfallPct = hourlyShortfallPct,
                hourlyEscalationLevel = hourlyEscalationLevel,
                checkpointWindowIndex = completedCheckpointWindow,
                checkpointMissed = checkpointMissed,
                checkpointShortfallPct = checkpointShortfallPct,
                checkpointEscalationLevel = checkpointEscalationLevel,
                forcedReplan = false,
                profitWindowOpen = false,
                targetSatisfied = false,
                overdriveAllowed = false,
                budgetBoostMultiplier = 1.0,
                reserveReliefPct = 0.0,
                executionBoostMultiplier = 1.0,
                extraSlots = 0,
                concentrationBoostPct = 0.0,
                rotationAgeHoursDelta = 0.0,
                rotationScoreGapDelta = 0.0,
                partialTakeProfitPnlDelta = 0.0,
                winnerRunPnlDelta = 0.0,
                meaningfulExitProfitDelta = 0.0,
                rationale = listOf(
                    "Daily loss limit breached: ${formatPct(config.dailyLossLimitPct)}.",
                    "Entry suspended until WIB midnight.",
                    "Exit protection remains active.",
                ),
            )
        }
        val overdriveAllowed = targetSatisfied &&
            (
                topCandidateQuality >= 0.84 ||
                    aiConsensus >= 0.72 ||
                    cycle.selectedSignal?.expectedNetProfitabilityPct?.let { it >= 3.8 } == true
                )
        val hourlyPressure = ((expectedProfitByNowPct - controllerProfitPct) / config.targetProfitPct).coerceIn(0.0, 1.0)
        val baseUrgency = when {
            targetSatisfied && !overdriveAllowed -> 0.0
            targetSatisfied && overdriveAllowed -> (
                0.24 +
                    ((topCandidateQuality - 0.78).coerceAtLeast(0.0) * 0.55) +
                    (aiConsensus * 0.18)
                ).coerceIn(0.20, 0.62)
            else -> (
                (gapPressure * 0.56) +
                    (behindSchedule * 0.15) +
                    (hourlyPressure * 0.22) +
                    (aiConsensus * 0.16) +
                    (if (checkpointMissed) 0.24 else 0.0) +
                    ((topCandidateQuality - 0.52).coerceAtLeast(0.0) * 0.28) +
                    (if (profitWindowOpen) 0.10 else 0.0) -
                    (drawdownPenalty * 0.30)
                ).coerceIn(0.0, 1.0)
        }
        val urgencyFloor = when {
            targetSatisfied -> 0.0
            checkpointMissed -> 0.78
            forcedReplan -> 0.64
            profitWindowOpen -> 0.30
            hourlyMissed -> (0.46 + (hourlyMissCount * 0.05)).coerceAtMost(0.60)
            else -> 0.0
        }
        val urgency = max(baseUrgency, urgencyFloor).coerceIn(0.0, 1.0)

        val budgetBoostMultiplier = max(
            (1.0 + (urgency * 0.32) + (aiConsensus * 0.08)).coerceIn(1.0, config.maxBudgetBoostMultiplier),
            when {
                checkpointMissed -> 1.12
                forcedReplan -> 1.08
                profitWindowOpen -> 1.04
                hourlyMissed -> 1.04
                else -> 1.0
            },
        ).coerceIn(1.0, config.maxBudgetBoostMultiplier)
        val executionBoostMultiplier = max(
            (1.0 + (urgency * 0.22) + (aiConsensus * 0.05)).coerceIn(1.0, config.maxExecutionBoostMultiplier),
            when {
                checkpointMissed -> 1.08
                forcedReplan -> 1.04
                profitWindowOpen -> 1.02
                hourlyMissed -> 1.02
                else -> 1.0
            },
        ).coerceIn(1.0, config.maxExecutionBoostMultiplier)
        val reserveReliefPct = max(
            (0.02 + (urgency * 0.02) + (aiConsensus * 0.01)).coerceIn(0.0, config.maxReserveReliefPct),
            when {
                checkpointMissed -> 0.03
                forcedReplan -> 0.02
                profitWindowOpen -> 0.015
                hourlyMissed -> 0.015
                else -> 0.02
            },
        ).coerceIn(0.0, config.maxReserveReliefPct)
        val extraSlots = when {
            currentEquity < config.minEquityForExtraSlotIdr -> 0
            targetSatisfied && topCandidateQuality >= 0.82 && aiConsensus >= 0.68 -> config.maxExtraSlots
            checkpointMissed && strongBenchCount >= 2 -> 1.coerceAtMost(config.maxExtraSlots)
            forcedReplan && strongBenchCount >= 2 -> 1.coerceAtMost(config.maxExtraSlots)
            hourlyMissed && strongBenchCount >= 2 -> 1.coerceAtMost(config.maxExtraSlots)
            strongBenchCount >= 3 &&
                profitWindowOpen &&
                currentEquity >= (config.minEquityForExtraSlotIdr * 1.10) -> 1.coerceAtMost(config.maxExtraSlots)
            else -> 0
        }
        val concentrationBoostPct = max(
            ((urgency * 0.06) + (aiConsensus * 0.02)).coerceIn(0.0, config.maxConcentrationBoostPct),
            when {
                checkpointMissed -> 0.06
                forcedReplan -> 0.05
                hourlyMissed -> 0.04
                profitWindowOpen -> 0.04
                else -> 0.03
            },
        ).coerceIn(0.0, config.maxConcentrationBoostPct)

        val rationale = buildList {
            add("Target harian ${formatPct(config.targetProfitPct)} dengan progress kontrol ${formatPct(progressPct * 100.0)}.")
            if (hourlyEvaluationWindow > 0) {
                add("Evaluasi 1 jam ke-$hourlyEvaluationWindow aktif: pace target meminta minimal ${formatPct(hourlyExpectedProfitPct)}.")
            }
            if (hourlyMissed) add("Evaluasi hourly miss ${hourlyMissCount} langkah pace (${formatPct(hourlyShortfallPct)} shortfall), jadi bot wajib menaikkan tekanan entry, sizing, dan rotasi.")
            if (profitWindowOpen && !targetSatisfied) add("Profit window terbuka: kandidat saat ini cukup kuat untuk tetap agresif meski checkpoint hanya jadi patokan.")
            if (targetSatisfied && overdriveAllowed) add("Target harian sudah lewat, tapi setup sangat kuat jadi bot tetap overdrive untuk kejar profit lanjutan.")
            if (targetSatisfied && !overdriveAllowed) add("Target harian sudah tercapai dan tidak ada setup ekstrem, jadi bot mulai jaga hasil.")
            if (targetGapPct > 0.0) add("Gap target tersisa ${formatPct(targetGapPct)} dan urgency ${formatPct(urgency * 100.0)}.")
            if (behindSchedule > 0.12) add("Bot tertinggal dari ritme target harian, jadi pursuit pressure dinaikkan.")
            if (hourlyPressure > 0.12) add("Evaluasi jam ini menunjukkan profit keras tertinggal dari pace harian, jadi sizing, rotasi, dan filter entry dipaksa lebih agresif.")
            if (checkpointMissed) add("Checkpoint 3 jam ke-$completedCheckpointWindow miss: target ${formatPct(checkpointExpectedProfitPct)} vs realisasi keras ${formatPct(checkpointProfitPct)}, jadi bot wajib replan agresif.")
            if (forcedReplan && !checkpointMissed) add("Gap hourly terlalu besar, jadi bot masuk forced replan sebelum checkpoint berikutnya.")
            if (aiConsensus >= 0.55) add("Consensus AI kuat, sizing dan fokus modal boleh dinaikkan.")
            if (extraSlots > 0) add("Bench pair cukup kuat untuk membuka ${extraSlots} slot tambahan tanpa mengorbankan fokus modal.")
        }

        return DailyTargetPursuit(
            phase = when {
                targetSatisfied && overdriveAllowed -> "OVERDRIVE"
                targetSatisfied -> "LOCK_PROFIT"
                urgency >= 0.72 -> "FULL_CHASE"
                urgency >= 0.42 -> "CHASE"
                else -> "TRACKING"
            },
            currentProfitPct = effectiveProfitPct,
            progressPct = progressPct,
            targetGapPct = targetGapPct,
            urgency = urgency,
            hourlyWindowIndex = hourlyEvaluationWindow,
            hourlyMissed = hourlyMissed,
            hourlyMissCount = hourlyMissCount,
            hourlyShortfallPct = hourlyShortfallPct,
            hourlyEscalationLevel = hourlyEscalationLevel,
            checkpointWindowIndex = completedCheckpointWindow,
            checkpointMissed = checkpointMissed,
            checkpointShortfallPct = checkpointShortfallPct,
            checkpointEscalationLevel = checkpointEscalationLevel,
            forcedReplan = forcedReplan,
            profitWindowOpen = profitWindowOpen,
            targetSatisfied = targetSatisfied,
            overdriveAllowed = overdriveAllowed,
            budgetBoostMultiplier = budgetBoostMultiplier,
            reserveReliefPct = reserveReliefPct,
            executionBoostMultiplier = executionBoostMultiplier,
            extraSlots = extraSlots,
            concentrationBoostPct = concentrationBoostPct,
            rotationAgeHoursDelta = (-0.10 - (urgency * 0.28) - (if (forcedReplan) 0.08 else 0.0)).coerceAtLeast(-0.46),
            rotationScoreGapDelta = (-0.02 - (urgency * 0.05) - (if (forcedReplan) 0.02 else 0.0)).coerceAtLeast(-0.10),
            partialTakeProfitPnlDelta = (urgency * 0.55).coerceAtMost(0.55),
            winnerRunPnlDelta = (-0.16 - (urgency * 0.22)).coerceAtLeast(-0.40),
            meaningfulExitProfitDelta = (-0.08 - (urgency * 0.18) - (if (checkpointMissed) 0.12 else 0.0) - (if (forcedReplan && !checkpointMissed) 0.06 else 0.0)).coerceAtLeast(-0.36),
            rationale = rationale,
        )
    }

    private fun expectedProfitAt(elapsedHours: Double): Double = when {
        elapsedHours <= 0.0 -> 0.0
        else -> {
            val checkpointWindow = kotlin.math.floor(elapsedHours / config.checkpointCadenceHours).toInt().coerceAtLeast(0)
            val checkpointStartHour = checkpointWindow * config.checkpointCadenceHours
            val previousTarget = if (checkpointWindow <= 0) 0.0 else checkpointTargetAtWindow(checkpointWindow)
            val nextWindow = checkpointWindow + 1
            val nextTarget = checkpointTargetAtWindow(nextWindow)
            val segmentProgress = ((elapsedHours - checkpointStartHour) / config.checkpointCadenceHours).coerceIn(0.0, 1.0)
            previousTarget + ((nextTarget - previousTarget) * segmentProgress)
        }
    }.coerceIn(0.0, config.targetProfitPct)

    private fun checkpointTargetAtWindow(window: Int): Double = when {
        window <= 0 -> 0.0
        window == 1 -> config.threeHourCheckpointPct
        window == 2 -> 14.0
        window == 3 -> 18.0
        window == 4 -> 21.0
        window == 5 -> 23.0
        else -> config.targetProfitPct
    }.coerceIn(0.0, config.targetProfitPct)

    private fun formatPct(value: Double): String = String.format("%.1f%%", value)
}
