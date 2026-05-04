package com.kibot.macengine.runtime

import com.kibot.core.ManagedPosition
import com.kibot.shared.models.MarketQuote
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.nio.file.Files
import java.nio.file.Path
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.sqrt
import kotlin.random.Random

@Serializable
data class LocalLearningMemoryFile(
    val generatedAtUtc: String? = null,
    val tradeEvents: List<LearningTradeEvent> = emptyList(),
    val pairProfiles: List<LearningPairProfile> = emptyList(),
)

@Serializable
data class LearningTradeEvent(
    val timestampUtc: String,
    val pairId: String,
    val bucketType: String,
    val orderType: String,
    val entryExpectedPrice: Double = 0.0,
    val entryRealizedPrice: Double = 0.0,
    val exitExpectedPrice: Double = 0.0,
    val exitRealizedPrice: Double = 0.0,
    val spreadPctAtEntry: Double = 0.0,
    val spreadPctAtExit: Double = 0.0,
    val entrySlippagePct: Double = 0.0,
    val exitSlippagePct: Double = 0.0,
    val netProfitPct: Double = 0.0,
    val holdMinutes: Double = 0.0,
    val exitReason: String = "",
)

@Serializable
data class LearningPairProfile(
    val pairId: String,
    val lastUpdatedUtc: String,
    val lastObservedMidPrice: Double = 0.0,
    val lastObservedVolume24h: Double = 0.0,
    val lastObservedAtEpochMs: Long = 0L,
    val previousVolumeVelocityPerMin: Double = 0.0,
    val avgObservedSpreadPct: Double = 0.0,
    val avgEntrySlippagePct: Double = 0.0,
    val ewmaVolatilityPct: Double = 0.0,
    val lastPriceVelocityPctPerMin: Double = 0.0,
    val jumpShockCount: Int = 0,
    val fakePumpCount: Int = 0,
    val spoofSuspicionCount: Int = 0,
    val leadLagSampleCount: Int = 0,
    val avgLeadLagDelayMs: Double = 0.0,
    val bounceSampleCount: Int = 0,
    val avgBounceRecoveryMinutes: Double = 0.0,
    val pendingShockAnchorPrice: Double = 0.0,
    val pendingShockLowPrice: Double = 0.0,
    val pendingShockDetectedUtc: String? = null,
    val aggressiveTradeCount: Int = 0,
    val aggressiveWinCount: Int = 0,
    val stableTradeCount: Int = 0,
    val stableWinCount: Int = 0,
    val avgAggressiveHoldMinutes: Double = 0.0,
    val recentLossEpochMs: List<Long> = emptyList(),
    val recentEntryRejectEpochMs: List<Long> = emptyList(),
    val entryRejectCount: Int = 0,
    val learningPolicyRejectCount: Int = 0,
    val lastFakePumpDetectedUtc: String? = null,
    val lastSpoofDetectedUtc: String? = null,
)

data class LearningRiskSnapshot(
    val historicalVar95Pct: Double = 0.0,
    val conditionalVar95Pct: Double = 0.0,
    val bootstrapVar95Pct: Double = 0.0,
    val bootstrapConditionalVar95Pct: Double = 0.0,
    val maxDrawdownPct: Double = 0.0,
    val ulcerIndex: Double = 0.0,
    val ruinProbability: Double = 0.0,
    val boundedKellyFraction: Double = 0.0,
    val sharpeLikeRatio: Double = 0.0,
    val sortinoLikeRatio: Double = 0.0,
    val skewness: Double = 0.0,
    val kurtosis: Double = 0.0,
)

data class LearningComputeProfile(
    val monteCarloScenarioCount: Int = 96,
    val monteCarloHorizonTrades: Int = 6,
    val maxTrackedPairs: Int = 18,
)

data class LocalLearningSnapshot(
    val pairTrustScores: Map<String, Double> = emptyMap(),
    val temporaryBlacklistPairs: List<String> = emptyList(),
    val forceLimitPairs: List<String> = emptyList(),
    val forceMarketPairs: List<String> = emptyList(),
    val tightenTrailingPairs: List<String> = emptyList(),
    val rotateNowPairs: List<String> = emptyList(),
    val holdLongerPairs: List<String> = emptyList(),
    val volatilityBrakePairs: List<String> = emptyList(),
    val hourlyAggressionMultiplier: Double = 1.0,
    val dailyAggressionBias: Double = 0.0,
    val risk: LearningRiskSnapshot = LearningRiskSnapshot(),
    val notes: List<String> = emptyList(),
)

class LocalLearningMemoryStore(
    private val path: Path,
) {
    private val json = Json {
        prettyPrint = true
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = true
    }
    private val lock = Any()
    private val retentionMs = 3L * 24L * 60L * 60L * 1000L
    private val tiltWindowMs = 2L * 60L * 60L * 1000L
    private val observationPersistIntervalMs = 20_000L
    private var memory = loadOrEmpty()
    private var lastObservedPersistEpochMs: Long = 0L

    fun recordTrade(event: LearningTradeEvent) {
        synchronized(lock) {
            pruneLocked(Instant.parse(event.timestampUtc))
            val events = memory.tradeEvents.toMutableList()
            events += event
            val pairKey = event.pairId.lowercase()
            val profiles = memory.pairProfiles.associateBy { it.pairId.lowercase() }.toMutableMap()
            val profile = profiles[pairKey] ?: LearningPairProfile(
                pairId = pairKey,
                lastUpdatedUtc = event.timestampUtc,
            )
            val timestamp = Instant.parse(event.timestampUtc)
            val isAggressive = event.bucketType.equals("AGGRESSIVE", ignoreCase = true)
            val isWin = event.netProfitPct > 0.0
            val recentLosses = (profile.recentLossEpochMs + listOfNotNull(
                timestamp.toEpochMilliseconds().takeIf { event.netProfitPct < 0.0 },
            )).filter { timestamp.toEpochMilliseconds() - it <= tiltWindowMs }
            profiles[pairKey] = profile.copy(
                lastUpdatedUtc = event.timestampUtc,
                avgObservedSpreadPct = smoothAverage(profile.avgObservedSpreadPct, listOf(event.spreadPctAtEntry, event.spreadPctAtExit).filter { it > 0.0 }.averageOrZero()),
                avgEntrySlippagePct = smoothAverage(profile.avgEntrySlippagePct, listOf(event.entrySlippagePct, event.exitSlippagePct).filter { it > 0.0 }.averageOrZero()),
                aggressiveTradeCount = profile.aggressiveTradeCount + if (isAggressive) 1 else 0,
                aggressiveWinCount = profile.aggressiveWinCount + if (isAggressive && isWin) 1 else 0,
                stableTradeCount = profile.stableTradeCount + if (!isAggressive) 1 else 0,
                stableWinCount = profile.stableWinCount + if (!isAggressive && isWin) 1 else 0,
                avgAggressiveHoldMinutes = if (isAggressive && event.holdMinutes > 0.0) {
                    smoothAverage(profile.avgAggressiveHoldMinutes, event.holdMinutes)
                } else {
                    profile.avgAggressiveHoldMinutes
                },
                recentLossEpochMs = recentLosses,
            )
            memory = memory.copy(
                generatedAtUtc = timestamp.toString(),
                tradeEvents = events.takeLast(1_200),
                pairProfiles = profiles.values.sortedBy { it.pairId },
            )
            persistLocked()
        }
    }

    fun recordLeadLagObservation(
        pairId: String,
        now: Instant,
        delayMs: Long,
    ) {
        if (delayMs <= 0L) return
        synchronized(lock) {
            pruneLocked(now)
            val nowMs = now.toEpochMilliseconds()
            val key = pairId.lowercase()
            val profiles = memory.pairProfiles.associateBy { it.pairId.lowercase() }.toMutableMap()
            val profile = profiles[key] ?: LearningPairProfile(pairId = key, lastUpdatedUtc = now.toString())
            profiles[key] = profile.copy(
                lastUpdatedUtc = now.toString(),
                leadLagSampleCount = profile.leadLagSampleCount + 1,
                avgLeadLagDelayMs = smoothAverage(profile.avgLeadLagDelayMs, delayMs.toDouble()),
            )
            memory = memory.copy(
                generatedAtUtc = now.toString(),
                pairProfiles = profiles.values.sortedBy { it.pairId },
            )
            if ((nowMs - lastObservedPersistEpochMs) >= observationPersistIntervalMs) {
                persistLocked()
                lastObservedPersistEpochMs = nowMs
            }
        }
    }

    fun observeMarketQuotes(
        now: Instant,
        marketQuotes: List<MarketQuote>,
        trackedPairs: Set<String>,
        spoofedPairs: Set<String>,
    ) {
        if (marketQuotes.isEmpty()) return
        synchronized(lock) {
            pruneLocked(now)
            val tracked = trackedPairs.map { it.lowercase() }.toSet()
            val profiles = memory.pairProfiles.associateBy { it.pairId.lowercase() }.toMutableMap()
            val nowMs = now.toEpochMilliseconds()
            marketQuotes.forEach { quote ->
                val key = quote.pairId.value.lowercase()
                if (tracked.isNotEmpty() && key !in tracked) return@forEach
                val profile = profiles[key] ?: LearningPairProfile(pairId = key, lastUpdatedUtc = now.toString())
                val mid = quote.midPrice.toDoubleOrZero()
                val vol = quote.quoteVolume24h.toDoubleOrZero()
                if (mid <= 0.0 || vol <= 0.0) return@forEach
                val lastAt = profile.lastObservedAtEpochMs
                val deltaMinutes = if (lastAt > 0L) ((nowMs - lastAt).coerceAtLeast(1L) / 60_000.0) else 0.0
                var updated = profile.copy(
                    lastUpdatedUtc = now.toString(),
                    lastObservedMidPrice = mid,
                    lastObservedVolume24h = vol,
                    lastObservedAtEpochMs = nowMs,
                    avgObservedSpreadPct = smoothAverage(profile.avgObservedSpreadPct, quote.spreadPct.coerceAtLeast(0.0)),
                )
                if (deltaMinutes > 0.0 && profile.lastObservedMidPrice > 0.0) {
                    val priceVelocityPctPerMin = (((mid - profile.lastObservedMidPrice) / profile.lastObservedMidPrice) * 100.0) / deltaMinutes
                    val logReturnPct = kotlin.math.abs(kotlin.math.ln((mid / profile.lastObservedMidPrice).coerceAtLeast(1e-9))) * 100.0
                    val volumeVelocityPerMin = ((vol - profile.lastObservedVolume24h).coerceAtLeast(0.0)) / deltaMinutes
                    val volumeFading = profile.previousVolumeVelocityPerMin > 0.0 &&
                        volumeVelocityPerMin < (profile.previousVolumeVelocityPerMin * 0.58)
                    val jumpShockDetected = kotlin.math.abs(priceVelocityPctPerMin) >= 1.6 || logReturnPct >= 2.2
                    val fakePump = priceVelocityPctPerMin >= 0.18 &&
                        volumeFading &&
                        quote.orderBookStabilityScore <= 0.68
                    if (fakePump && shouldRegisterEvent(now, profile.lastFakePumpDetectedUtc, cooldownMs = 90_000L)) {
                        updated = updated.copy(
                            fakePumpCount = updated.fakePumpCount + 1,
                            lastFakePumpDetectedUtc = now.toString(),
                        )
                    }
                    val drawdownPct = ((mid - profile.lastObservedMidPrice) / profile.lastObservedMidPrice) * 100.0
                    if (drawdownPct <= -3.0) {
                        updated = updated.copy(
                            pendingShockAnchorPrice = profile.lastObservedMidPrice,
                            pendingShockLowPrice = mid,
                            pendingShockDetectedUtc = now.toString(),
                        )
                    } else if (updated.pendingShockDetectedUtc != null && updated.pendingShockAnchorPrice > 0.0) {
                        val lowPrice = minOf(updated.pendingShockLowPrice.takeIf { it > 0.0 } ?: mid, mid)
                    val recovered = mid >= (updated.pendingShockAnchorPrice * 0.995)
                    updated = updated.copy(pendingShockLowPrice = lowPrice)
                    if (recovered) {
                            val shockAt = Instant.parse(updated.pendingShockDetectedUtc!!)
                            val recoveryMinutes = ((now.toEpochMilliseconds() - shockAt.toEpochMilliseconds()).coerceAtLeast(0L) / 60_000.0)
                            updated = updated.copy(
                                bounceSampleCount = updated.bounceSampleCount + 1,
                                avgBounceRecoveryMinutes = smoothAverage(updated.avgBounceRecoveryMinutes, recoveryMinutes),
                                pendingShockAnchorPrice = 0.0,
                                pendingShockLowPrice = 0.0,
                                pendingShockDetectedUtc = null,
                            )
                        }
                    }
                    updated = updated.copy(previousVolumeVelocityPerMin = volumeVelocityPerMin)
                    updated = updated.copy(
                        ewmaVolatilityPct = smoothAverage(updated.ewmaVolatilityPct, logReturnPct, alpha = 0.22),
                        lastPriceVelocityPctPerMin = priceVelocityPctPerMin,
                        jumpShockCount = updated.jumpShockCount + if (
                            jumpShockDetected && shouldRegisterEvent(now, updated.lastFakePumpDetectedUtc, cooldownMs = 45_000L)
                        ) 1 else 0,
                    )
                }
                if (key in spoofedPairs && shouldRegisterEvent(now, updated.lastSpoofDetectedUtc, cooldownMs = 75_000L)) {
                    updated = updated.copy(
                        spoofSuspicionCount = updated.spoofSuspicionCount + 1,
                        lastSpoofDetectedUtc = now.toString(),
                    )
                }
                profiles[key] = updated
            }
            memory = memory.copy(
                generatedAtUtc = now.toString(),
                pairProfiles = profiles.values.sortedBy { it.pairId },
            )
            persistLocked()
        }
    }

    fun recordEntryRejection(
        now: Instant,
        pairId: String,
        reason: String,
    ) {
        val key = pairId.lowercase()
        if (!looksLikePairId(key)) return
        synchronized(lock) {
            pruneLocked(now)
            val nowMs = now.toEpochMilliseconds()
            val normalizedReason = reason.trim().lowercase()
            val profiles = memory.pairProfiles.associateBy { it.pairId.lowercase() }.toMutableMap()
            val profile = profiles[key] ?: LearningPairProfile(pairId = key, lastUpdatedUtc = now.toString())
            val recentRejects = (profile.recentEntryRejectEpochMs + nowMs)
                .filter { nowMs - it <= tiltWindowMs }
            val learningBlocked = normalizedReason.contains("learning_policy_blocked") ||
                normalizedReason.contains("trinity_heartbeat_safe_mode") ||
                normalizedReason.contains("risk ladder hard stop")
            val liquidityStress = normalizedReason.contains("spread_cap_enforcement_failed") ||
                normalizedReason.contains("liquidity_guard_failed") ||
                normalizedReason.contains("order_chase_failed")
            profiles[key] = profile.copy(
                lastUpdatedUtc = now.toString(),
                recentEntryRejectEpochMs = recentRejects,
                entryRejectCount = profile.entryRejectCount + 1,
                learningPolicyRejectCount = profile.learningPolicyRejectCount + if (learningBlocked) 1 else 0,
                spoofSuspicionCount = profile.spoofSuspicionCount + if (liquidityStress) 1 else 0,
                lastSpoofDetectedUtc = if (liquidityStress) now.toString() else profile.lastSpoofDetectedUtc,
            )
            memory = memory.copy(
                generatedAtUtc = now.toString(),
                pairProfiles = profiles.values.sortedBy { it.pairId },
            )
            if ((nowMs - lastObservedPersistEpochMs) >= observationPersistIntervalMs) {
                persistLocked()
                lastObservedPersistEpochMs = nowMs
            }
        }
    }

    fun snapshot(
        now: Instant,
        dailyPnlPct: Double,
        holdings: List<ManagedPosition>,
        computeProfile: LearningComputeProfile = LearningComputeProfile(),
    ): LocalLearningSnapshot {
        synchronized(lock) {
            pruneLocked(now)
            val currentHour = now.toLocalDateTime(TimeZone.of("Asia/Jakarta")).hour
            val aggressiveTrades = memory.tradeEvents.filter { it.bucketType.equals("AGGRESSIVE", ignoreCase = true) }
            val recentReturns = memory.tradeEvents
                .takeLast(96)
                .map { it.netProfitPct }
                .filter { it.isFinite() }
            val risk = buildRiskSnapshot(recentReturns, computeProfile)
            val hourTrades = aggressiveTrades.filter {
                runCatching { Instant.parse(it.timestampUtc).toLocalDateTime(TimeZone.of("Asia/Jakarta")).hour == currentHour }.getOrDefault(false)
            }
            val hourWinRate = hourTrades.takeIf { it.isNotEmpty() }?.let { trades ->
                trades.count { it.netProfitPct > 0.0 }.toDouble() / trades.size.toDouble()
            } ?: 0.5
            val hourAvgPnl = hourTrades.map { it.netProfitPct }.averageOrZero()
            val hourlyAggressionMultiplier = when {
                risk.ruinProbability >= 0.35 -> 0.60
                risk.bootstrapConditionalVar95Pct <= -3.5 -> 0.66
                risk.maxDrawdownPct >= 6.0 -> 0.72
                hourTrades.size >= 3 && hourWinRate < 0.40 -> 0.72
                hourTrades.size >= 3 && hourAvgPnl < 0.0 -> 0.78
                hourTrades.size >= 3 && hourWinRate >= 0.65 && hourAvgPnl > 0.35 -> 1.18
                hourTrades.size >= 2 && hourWinRate >= 0.55 && hourAvgPnl > 0.15 -> 1.08
                else -> 1.0
            }
            val dailyAggressionBias = when {
                risk.ruinProbability >= 0.45 -> -0.28
                risk.bootstrapConditionalVar95Pct <= -4.0 -> -0.20
                risk.maxDrawdownPct >= 7.0 -> -0.18
                dailyPnlPct <= -3.0 -> -0.22
                dailyPnlPct <= -1.5 -> -0.14
                risk.boundedKellyFraction >= 0.18 && risk.ruinProbability <= 0.12 && dailyPnlPct >= 2.0 -> 0.10
                dailyPnlPct >= 10.0 -> 0.16
                dailyPnlPct >= 5.0 -> 0.08
                else -> 0.0
            }

            val holdingPairs = holdings.associateBy { it.pairId.value.lowercase() }
            val pairTrust = memory.pairProfiles.associate { profile ->
                val key = profile.pairId.lowercase()
                val aggressiveWinRate = if (profile.aggressiveTradeCount > 0) {
                    profile.aggressiveWinCount.toDouble() / profile.aggressiveTradeCount.toDouble()
                } else {
                    0.5
                }
                val recentLossCount = profile.recentLossEpochMs.count { now.toEpochMilliseconds() - it <= tiltWindowMs }
                val recentRejectCount = profile.recentEntryRejectEpochMs.count { now.toEpochMilliseconds() - it <= tiltWindowMs }
                val trust = (
                    0.82 +
                        ((aggressiveWinRate - 0.5) * 0.34) -
                        (profile.avgEntrySlippagePct.coerceAtLeast(0.0) * 0.14) -
                        (profile.avgObservedSpreadPct.coerceAtLeast(0.0) * 0.05) -
                        (profile.fakePumpCount.coerceAtMost(6) * 0.045) -
                        (profile.spoofSuspicionCount.coerceAtMost(6) * 0.055) -
                        (recentLossCount.coerceAtMost(4) * 0.10) -
                        (recentRejectCount.coerceAtMost(6) * 0.035)
                    ).coerceIn(0.05, 1.10)
                key to trust
            }
            val temporaryBlacklistPairs = memory.pairProfiles.filter { profile ->
                val recentLossCount = profile.recentLossEpochMs.count { now.toEpochMilliseconds() - it <= tiltWindowMs }
                val recentRejectCount = profile.recentEntryRejectEpochMs.count { now.toEpochMilliseconds() - it <= tiltWindowMs }
                recentLossCount >= 3 ||
                    recentRejectCount >= 4 ||
                    profile.learningPolicyRejectCount >= 3 ||
                    (pairTrust[profile.pairId.lowercase()] ?: 1.0) <= 0.32
            }.map { it.pairId.lowercase() }
            val forceLimitPairs = memory.pairProfiles.filter { profile ->
                profile.spoofSuspicionCount >= 2 ||
                    profile.avgEntrySlippagePct >= 0.85 ||
                    profile.ewmaVolatilityPct >= 2.4 ||
                    (profile.leadLagSampleCount >= 2 && profile.avgLeadLagDelayMs <= 1200.0)
            }.map { it.pairId.lowercase() }
            val forceMarketPairs = memory.pairProfiles.filter { profile ->
                val trust = pairTrust[profile.pairId.lowercase()] ?: 0.5
                profile.leadLagSampleCount >= 2 &&
                    profile.avgLeadLagDelayMs >= 2500.0 &&
                    profile.ewmaVolatilityPct <= 2.1 &&
                    trust >= 0.48 &&
                    profile.spoofSuspicionCount == 0
            }.map { it.pairId.lowercase() }
            val volatilityBrakePairs = memory.pairProfiles.filter { profile ->
                profile.ewmaVolatilityPct >= 2.6 || profile.jumpShockCount >= 2
            }.map { it.pairId.lowercase() }
            val tightenTrailingPairs = holdings.filter { holding ->
                val profile = memory.pairProfiles.firstOrNull { it.pairId.equals(holding.pairId.value, ignoreCase = true) } ?: return@filter false
                profile.fakePumpCount >= 2 ||
                    profile.ewmaVolatilityPct >= 2.3 ||
                    profile.jumpShockCount >= 2 ||
                    (profile.avgAggressiveHoldMinutes in 0.1..12.0 && holding.unrealizedPnlPct >= 0.65)
            }.map { it.pairId.value.lowercase() }
            val rotateNowPairs = holdings.filter { holding ->
                val key = holding.pairId.value.lowercase()
                key in temporaryBlacklistPairs ||
                    key in volatilityBrakePairs ||
                    (pairTrust[key] ?: 1.0) <= 0.45
            }.map { it.pairId.value.lowercase() }
            val holdLongerPairs = holdings.filter { holding ->
                val profile = memory.pairProfiles.firstOrNull { it.pairId.equals(holding.pairId.value, ignoreCase = true) } ?: return@filter false
                holding.unrealizedPnlPct > 1.0 &&
                    (pairTrust[holding.pairId.value.lowercase()] ?: 0.0) >= 0.66 &&
                    (profile.avgBounceRecoveryMinutes == 0.0 || profile.avgBounceRecoveryMinutes <= 8.0)
            }.map { it.pairId.value.lowercase() }
            val notes = buildList {
                if (hourlyAggressionMultiplier < 0.9) add("Jam sekarang historisnya kurang ramah buat sleeve agresif; throttle agresi diturunkan.")
                if (dailyAggressionBias < 0.0) add("PnL harian merah; reserve dan profit-lock dibuat lebih defensif.")
                if (temporaryBlacklistPairs.isNotEmpty()) add("Micro-tilt protection aktif untuk ${temporaryBlacklistPairs.take(3).joinToString(",")}.")
                val rejectionHotPairs = memory.pairProfiles
                    .filter { profile -> profile.recentEntryRejectEpochMs.count { now.toEpochMilliseconds() - it <= tiltWindowMs } >= 3 }
                    .map { it.pairId.lowercase() }
                if (rejectionHotPairs.isNotEmpty()) add("Pair sering ditolak di 2 jam terakhir (${rejectionHotPairs.take(3).joinToString(",")}), sistem menurunkan prioritas pair tersebut.")
                if (forceLimitPairs.isNotEmpty()) add("Manipulasi/slippage tinggi terdeteksi; paksa limit order untuk ${forceLimitPairs.take(3).joinToString(",")}.")
                if (forceMarketPairs.isNotEmpty()) add("Latency lead-lag tinggi; market order taktis diizinkan untuk ${forceMarketPairs.take(3).joinToString(",")}.")
                if (volatilityBrakePairs.isNotEmpty()) add("Volatilitas/jump shock tinggi; rem entry dan trailing diperketat untuk ${volatilityBrakePairs.take(3).joinToString(",")}.")
                if (risk.bootstrapConditionalVar95Pct < 0.0) add("Stress tail risk ~ ${formatPct(risk.bootstrapConditionalVar95Pct)}; sleeve agresif ditahan lebih disiplin.")
                if (risk.maxDrawdownPct > 0.0) add("Drawdown historis lokal ${formatPct(-risk.maxDrawdownPct)} jadi acuan rem agresi.")
            }
            return LocalLearningSnapshot(
                pairTrustScores = pairTrust,
                temporaryBlacklistPairs = temporaryBlacklistPairs.distinct(),
                forceLimitPairs = forceLimitPairs.distinct(),
                forceMarketPairs = forceMarketPairs.distinct(),
                tightenTrailingPairs = tightenTrailingPairs.distinct(),
                rotateNowPairs = rotateNowPairs.distinct(),
                holdLongerPairs = holdLongerPairs.distinct(),
                volatilityBrakePairs = volatilityBrakePairs.distinct(),
                hourlyAggressionMultiplier = hourlyAggressionMultiplier,
                dailyAggressionBias = dailyAggressionBias,
                risk = risk,
                notes = notes,
            )
        }
    }

    private fun loadOrEmpty(): LocalLearningMemoryFile {
        return runCatching {
            if (!Files.exists(path)) return LocalLearningMemoryFile()
            val raw = Files.readString(path)
            if (raw.isBlank()) return LocalLearningMemoryFile()
            json.decodeFromString(LocalLearningMemoryFile.serializer(), raw)
        }.getOrElse { LocalLearningMemoryFile() }
    }

    private fun pruneLocked(now: Instant) {
        val cutoff = now.toEpochMilliseconds() - retentionMs
        val events = memory.tradeEvents.filter {
            runCatching { Instant.parse(it.timestampUtc).toEpochMilliseconds() >= cutoff }.getOrDefault(false)
        }
        val profiles = memory.pairProfiles.mapNotNull { profile ->
            val updatedAtMs = runCatching { Instant.parse(profile.lastUpdatedUtc).toEpochMilliseconds() }.getOrDefault(0L)
            if (updatedAtMs < cutoff && profile.recentLossEpochMs.none { now.toEpochMilliseconds() - it <= tiltWindowMs }) {
                null
            } else {
                profile.copy(
                    recentLossEpochMs = profile.recentLossEpochMs.filter { now.toEpochMilliseconds() - it <= tiltWindowMs },
                    recentEntryRejectEpochMs = profile.recentEntryRejectEpochMs.filter { now.toEpochMilliseconds() - it <= tiltWindowMs },
                )
            }
        }
        memory = memory.copy(
            generatedAtUtc = now.toString(),
            tradeEvents = events.takeLast(1_200),
            pairProfiles = profiles,
        )
    }

    private fun persistLocked() {
        runCatching {
            val parent = path.parent
            if (parent != null) Files.createDirectories(parent)
            Files.writeString(path, json.encodeToString(memory))
        }
    }

    private fun smoothAverage(current: Double, incoming: Double, alpha: Double = 0.35): Double {
        if (incoming <= 0.0) return current
        if (current <= 0.0) return incoming
        return ((current * (1.0 - alpha)) + (incoming * alpha)).coerceAtLeast(0.0)
    }

    private fun shouldRegisterEvent(now: Instant, lastEventUtc: String?, cooldownMs: Long): Boolean {
        val last = lastEventUtc?.let { runCatching { Instant.parse(it) }.getOrNull() } ?: return true
        return (now.toEpochMilliseconds() - last.toEpochMilliseconds()) >= cooldownMs
    }

    private fun looksLikePairId(pairId: String): Boolean {
        return pairId.contains('_') && pairId.none { it.isWhitespace() }
    }

    private fun buildRiskSnapshot(
        returnsPct: List<Double>,
        computeProfile: LearningComputeProfile,
    ): LearningRiskSnapshot {
        if (returnsPct.size < 4) return LearningRiskSnapshot()
        val sorted = returnsPct.sorted()
        val varIndex = ((sorted.size - 1) * 0.05).toInt().coerceIn(0, sorted.lastIndex)
        val historicalVar = sorted[varIndex]
        val cvarSample = sorted.filter { it <= historicalVar }
        val historicalCvar = cvarSample.averageOrZero()

        val scenarios = bootstrapMonteCarlo(
            returnsPct,
            scenarioCount = computeProfile.monteCarloScenarioCount,
            horizon = minOf(returnsPct.size, computeProfile.monteCarloHorizonTrades),
        )
        val sortedScenarios = scenarios.sorted()
        val scenarioVarIndex = ((sortedScenarios.size - 1) * 0.05).toInt().coerceIn(0, sortedScenarios.lastIndex)
        val bootstrapVar = sortedScenarios[scenarioVarIndex]
        val bootstrapCvar = sortedScenarios.filter { it <= bootstrapVar }.averageOrZero()

        val equityCurve = buildEquityCurve(returnsPct)
        val drawdowns = equityCurve.drawdowns()
        val maxDrawdownPct = drawdowns.maxOrNull()?.times(100.0) ?: 0.0
        val ulcerIndex = sqrt(drawdowns.map { (it * 100.0).pow(2) }.averageOrZero())

        val wins = returnsPct.filter { it > 0.0 }
        val losses = returnsPct.filter { it < 0.0 }
        val winRate = wins.size.toDouble() / returnsPct.size.toDouble()
        val avgWin = wins.map { it / 100.0 }.averageOrZero()
        val avgLoss = abs(losses.map { it / 100.0 }.averageOrZero())
        val rawKelly = if (avgLoss > 0.0) {
            winRate - ((1.0 - winRate) / (avgWin / avgLoss).coerceAtLeast(1e-6))
        } else {
            0.0
        }
        val boundedKelly = rawKelly.coerceIn(0.0, 0.20)
        val ruinProbability = estimateRuinProbability(scenarios, hardLossPct = -5.0)
        val meanReturn = returnsPct.averageOrZero()
        val stdDev = standardDeviation(returnsPct)
        val downsideDev = standardDeviation(returnsPct.filter { it < 0.0 })
        val sharpeLike = if (stdDev > 1e-6) meanReturn / stdDev else 0.0
        val sortinoLike = if (downsideDev > 1e-6) meanReturn / downsideDev else 0.0
        val skewness = centralMoment(returnsPct, 3)
        val kurtosis = centralMoment(returnsPct, 4)

        return LearningRiskSnapshot(
            historicalVar95Pct = historicalVar,
            conditionalVar95Pct = historicalCvar,
            bootstrapVar95Pct = bootstrapVar,
            bootstrapConditionalVar95Pct = bootstrapCvar,
            maxDrawdownPct = maxDrawdownPct,
            ulcerIndex = ulcerIndex,
            ruinProbability = ruinProbability,
            boundedKellyFraction = boundedKelly,
            sharpeLikeRatio = sharpeLike,
            sortinoLikeRatio = sortinoLike,
            skewness = skewness,
            kurtosis = kurtosis,
        )
    }

    private fun bootstrapMonteCarlo(
        returnsPct: List<Double>,
        scenarioCount: Int,
        horizon: Int,
    ): List<Double> {
        if (returnsPct.isEmpty()) return emptyList()
        val seed = returnsPct.fold(17L) { acc, value -> (acc * 31L) + value.toBits() }
        val random = Random(seed)
        return List(scenarioCount.coerceAtLeast(16)) {
            var equity = 1.0
            repeat(horizon.coerceAtLeast(1)) {
                val sampled = returnsPct[random.nextInt(returnsPct.size)] / 100.0
                equity *= (1.0 + sampled)
            }
            (equity - 1.0) * 100.0
        }
    }

    private fun buildEquityCurve(returnsPct: List<Double>): List<Double> {
        var equity = 1.0
        return returnsPct.map { value ->
            equity *= (1.0 + (value / 100.0))
            equity
        }
    }

    private fun List<Double>.drawdowns(): List<Double> {
        var peak = 1.0
        return map { equity ->
            peak = maxOf(peak, equity)
            if (peak <= 0.0) 0.0 else ((peak - equity) / peak).coerceAtLeast(0.0)
        }
    }

    private fun estimateRuinProbability(
        scenarioReturnsPct: List<Double>,
        hardLossPct: Double,
    ): Double {
        if (scenarioReturnsPct.isEmpty()) return 0.0
        return scenarioReturnsPct.count { it <= hardLossPct }.toDouble() / scenarioReturnsPct.size.toDouble()
    }

    private fun standardDeviation(values: List<Double>): Double {
        if (values.size < 2) return 0.0
        val mean = values.averageOrZero()
        return sqrt(values.map { (it - mean).pow(2) }.averageOrZero())
    }

    private fun centralMoment(values: List<Double>, order: Int): Double {
        if (values.size < 3) return 0.0
        val mean = values.averageOrZero()
        val std = standardDeviation(values)
        if (std <= 1e-6) return 0.0
        return values.map { ((it - mean) / std).pow(order) }.averageOrZero()
    }

    private fun formatPct(value: Double): String = "${"%.2f".format(value)}%"
}

private fun List<Double>.averageOrZero(): Double = if (isEmpty()) 0.0 else average()
