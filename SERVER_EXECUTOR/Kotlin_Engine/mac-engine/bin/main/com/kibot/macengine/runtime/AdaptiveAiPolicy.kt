package com.kibot.macengine.runtime

import com.kibot.shared.models.AiPairSupportHint
import com.kibot.shared.models.PairId
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.nio.file.Files
import java.nio.file.Path

@Serializable
data class AdaptiveAiPolicyFile(
    @SerialName("generated_at_utc") val generatedAtUtc: String? = null,
    @SerialName("policy_ttl_minutes") val policyTtlMinutes: Int? = null,
    @SerialName("successful_providers") val successfulProviders: List<String> = emptyList(),
    @SerialName("consensus_strength") val consensusStrength: Double = 0.0,
    @SerialName("focus_pairs") val focusPairs: List<String> = emptyList(),
    @SerialName("pair_biases") val pairBiases: List<AdaptiveAiPairBias> = emptyList(),
    val adjustments: AdaptiveAiAdjustments = AdaptiveAiAdjustments(),
    val execution: AdaptiveAiExecutionFile = AdaptiveAiExecutionFile(),
    val watchdog: AdaptiveAiWatchdogFile = AdaptiveAiWatchdogFile(),
)

@Serializable
data class AdaptiveAiPairBias(
    @SerialName("pair_id") val pairId: String,
    @SerialName("support_bias") val supportBias: Double = 0.0,
    @SerialName("caution_bias") val cautionBias: Double = 0.0,
    val rationale: String = "",
)

@Serializable
data class AdaptiveAiAdjustments(
    @SerialName("ranking_bias_scale") val rankingBiasScale: Double = 1.0,
    @SerialName("rotation_age_hours_delta") val rotationAgeHoursDelta: Double = 0.0,
    @SerialName("rotation_score_gap_delta") val rotationScoreGapDelta: Double = 0.0,
    @SerialName("partial_take_profit_pnl_delta") val partialTakeProfitPnlDelta: Double = 0.0,
    @SerialName("winner_run_pnl_delta") val winnerRunPnlDelta: Double = 0.0,
    @SerialName("meaningful_exit_profit_delta") val meaningfulExitProfitDelta: Double = 0.0,
    @SerialName("budget_boost_multiplier_delta") val budgetBoostMultiplierDelta: Double = 0.0,
    @SerialName("reserve_relief_pct_delta") val reserveReliefPctDelta: Double = 0.0,
    @SerialName("allocation_focus_pct_delta") val allocationFocusPctDelta: Double = 0.0,
    @SerialName("extra_slots_delta") val extraSlotsDelta: Int = 0,
)

@Serializable
data class AdaptiveAiExecutionFile(
    @SerialName("rotate_now_pairs") val rotateNowPairs: List<String> = emptyList(),
    @SerialName("hold_longer_pairs") val holdLongerPairs: List<String> = emptyList(),
    @SerialName("temporary_blacklist_pairs") val temporaryBlacklistPairs: List<String> = emptyList(),
    @SerialName("force_limit_pairs") val forceLimitPairs: List<String> = emptyList(),
    @SerialName("force_market_pairs") val forceMarketPairs: List<String> = emptyList(),
    @SerialName("tight_trailing_pairs") val tightTrailingPairs: List<String> = emptyList(),
    @SerialName("concentration_pair") val concentrationPair: String? = null,
    @SerialName("avoid_pair_families") val avoidPairFamilies: List<String> = emptyList(),
    @SerialName("replacement_hints") val replacementHints: List<AdaptiveAiReplacementFile> = emptyList(),
    @SerialName("learning_notes") val learningNotes: List<String> = emptyList(),
)

@Serializable
data class AdaptiveAiWatchdogFile(
    val status: String = "IDLE",
    val severity: String = "LOW",
    val reprimand: String = "",
    @SerialName("root_causes") val rootCauses: List<String> = emptyList(),
    @SerialName("required_actions") val requiredActions: List<String> = emptyList(),
    @SerialName("force_rotation") val forceRotation: Boolean = false,
    @SerialName("force_concentration") val forceConcentration: Boolean = false,
    @SerialName("pressure_floor") val pressureFloor: Double = 0.0,
    @SerialName("budget_boost_floor") val budgetBoostFloor: Double = 1.0,
    @SerialName("execution_boost_floor") val executionBoostFloor: Double = 1.0,
    @SerialName("reserve_relief_floor") val reserveReliefFloor: Double = 0.0,
)

@Serializable
data class AdaptiveAiReplacementFile(
    @SerialName("cut_pair") val cutPair: String,
    @SerialName("replace_pair") val replacePair: String,
    val rationale: String = "",
)

data class AdaptiveAiExecutionHints(
    val rotateNowPairs: List<PairId> = emptyList(),
    val holdLongerPairs: List<PairId> = emptyList(),
    val temporaryBlacklistPairs: List<PairId> = emptyList(),
    val forceLimitPairs: List<PairId> = emptyList(),
    val forceMarketPairs: List<PairId> = emptyList(),
    val tightTrailingPairs: List<PairId> = emptyList(),
    val concentrationPair: PairId? = null,
    val avoidPairFamilies: List<String> = emptyList(),
    val replacementHints: List<AdaptiveAiReplacementHint> = emptyList(),
    val learningNotes: List<String> = emptyList(),
)

data class AdaptiveAiReplacementHint(
    val cutPair: PairId,
    val replacePair: PairId,
    val rationale: String = "",
)

data class AdaptiveAiPolicy(
    val generatedAt: Instant? = null,
    val policyTtlMinutes: Int? = null,
    val successfulProviders: List<String> = emptyList(),
    val consensusStrength: Double = 0.0,
    val pairHints: List<AiPairSupportHint> = emptyList(),
    val adjustments: AdaptiveAiAdjustments = AdaptiveAiAdjustments(),
    val executionHints: AdaptiveAiExecutionHints = AdaptiveAiExecutionHints(),
    val watchdog: AdaptiveAiWatchdog = AdaptiveAiWatchdog(),
) {
    val isActive: Boolean = successfulProviders.isNotEmpty() || pairHints.isNotEmpty()
}

data class AdaptiveAiWatchdog(
    val status: String = "IDLE",
    val severity: String = "LOW",
    val reprimand: String = "",
    val rootCauses: List<String> = emptyList(),
    val requiredActions: List<String> = emptyList(),
    val forceRotation: Boolean = false,
    val forceConcentration: Boolean = false,
    val pressureFloor: Double = 0.0,
    val budgetBoostFloor: Double = 1.0,
    val executionBoostFloor: Double = 1.0,
    val reserveReliefFloor: Double = 0.0,
)

class AdaptiveAiPolicyLoader(
    private val path: Path,
    private val maxPolicyAgeHours: Double = 2.5,
) {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = true
    }

    fun loadOrNull(now: Instant = Clock.System.now()): AdaptiveAiPolicy? {
        if (!Files.exists(path)) return null
        val raw = Files.readString(path)
        if (raw.isBlank()) return null
        val parsed = json.decodeFromString(AdaptiveAiPolicyFile.serializer(), raw)
        val generatedAt = runCatching { parsed.generatedAtUtc?.let(Instant::parse) }.getOrNull()
        if (generatedAt != null) {
            val ageHours = ((now.toEpochMilliseconds() - generatedAt.toEpochMilliseconds()).coerceAtLeast(0L) / 3_600_000.0)
            val ttlHours = ((parsed.policyTtlMinutes ?: (maxPolicyAgeHours * 60).toInt()).coerceAtLeast(30)) / 60.0
            if (ageHours > minOf(maxPolicyAgeHours, ttlHours)) return null
        }
        val pairHints = parsed.pairBiases.mapNotNull { bias ->
            val pair = bias.pairId.trim().lowercase()
            if (pair.isBlank()) return@mapNotNull null
            AiPairSupportHint(
                pairId = PairId(pair),
                supportBias = bias.supportBias.coerceIn(0.0, 0.08),
                cautionBias = bias.cautionBias.coerceIn(0.0, 0.06),
                cheapNominalWatch = false,
                rationale = bias.rationale.ifBlank { "Adaptive AI policy" },
                generatedAt = generatedAt ?: now,
            )
        }
        return AdaptiveAiPolicy(
            generatedAt = generatedAt,
            policyTtlMinutes = parsed.policyTtlMinutes,
            successfulProviders = parsed.successfulProviders,
            consensusStrength = parsed.consensusStrength.coerceIn(0.0, 1.0),
            pairHints = pairHints,
            adjustments = parsed.adjustments,
            executionHints = AdaptiveAiExecutionHints(
                rotateNowPairs = parsed.execution.rotateNowPairs.mapNotNull { it.trim().lowercase().takeIf(String::isNotBlank)?.let(::PairId) },
                holdLongerPairs = parsed.execution.holdLongerPairs.mapNotNull { it.trim().lowercase().takeIf(String::isNotBlank)?.let(::PairId) },
                temporaryBlacklistPairs = parsed.execution.temporaryBlacklistPairs.mapNotNull { it.trim().lowercase().takeIf(String::isNotBlank)?.let(::PairId) },
                forceLimitPairs = parsed.execution.forceLimitPairs.mapNotNull { it.trim().lowercase().takeIf(String::isNotBlank)?.let(::PairId) },
                forceMarketPairs = parsed.execution.forceMarketPairs.mapNotNull { it.trim().lowercase().takeIf(String::isNotBlank)?.let(::PairId) },
                tightTrailingPairs = parsed.execution.tightTrailingPairs.mapNotNull { it.trim().lowercase().takeIf(String::isNotBlank)?.let(::PairId) },
                concentrationPair = parsed.execution.concentrationPair?.trim()?.lowercase()?.takeIf { it.isNotBlank() }?.let(::PairId),
                avoidPairFamilies = parsed.execution.avoidPairFamilies.mapNotNull { it.trim().lowercase().takeIf(String::isNotBlank) }.distinct(),
                replacementHints = parsed.execution.replacementHints.mapNotNull { hint ->
                    val cutPair = hint.cutPair.trim().lowercase().takeIf(String::isNotBlank)?.let(::PairId) ?: return@mapNotNull null
                    val replacePair = hint.replacePair.trim().lowercase().takeIf(String::isNotBlank)?.let(::PairId) ?: return@mapNotNull null
                    if (cutPair == replacePair) return@mapNotNull null
                    AdaptiveAiReplacementHint(
                        cutPair = cutPair,
                        replacePair = replacePair,
                        rationale = hint.rationale.trim(),
                    )
                },
                learningNotes = parsed.execution.learningNotes.map(String::trim).filter(String::isNotBlank),
            ),
            watchdog = AdaptiveAiWatchdog(
                status = parsed.watchdog.status.uppercase().ifBlank { "IDLE" },
                severity = parsed.watchdog.severity.uppercase().ifBlank { "LOW" },
                reprimand = parsed.watchdog.reprimand.trim(),
                rootCauses = parsed.watchdog.rootCauses.map(String::trim).filter(String::isNotBlank),
                requiredActions = parsed.watchdog.requiredActions.map(String::trim).filter(String::isNotBlank),
                forceRotation = parsed.watchdog.forceRotation,
                forceConcentration = parsed.watchdog.forceConcentration,
                pressureFloor = parsed.watchdog.pressureFloor.coerceIn(0.0, 1.0),
                budgetBoostFloor = parsed.watchdog.budgetBoostFloor.coerceIn(0.70, 2.1),
                executionBoostFloor = parsed.watchdog.executionBoostFloor.coerceIn(1.0, 1.95),
                reserveReliefFloor = parsed.watchdog.reserveReliefFloor.coerceIn(0.0, 0.14),
            ),
        )
    }
}
