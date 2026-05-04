package com.kibot.core

import com.kibot.shared.models.PairId
import kotlinx.serialization.Serializable

@Serializable
data class PairMicroPulseSample(
    val atEpochMs: Long,
    val midPrice: Double,
)

@Serializable
data class LocalTrailingSnapshot(
    val pair: PairId,
    val entryPrice: Double,
    val peakPrice: Double,
    val currentBid: Double,
    val floorPrice: Double,
    val dynamicTrailingStopPct: Double,
    val armed: Boolean,
    val retroactivePeakApplied: Boolean = false,
)

@Serializable
data class ForcedSellSignal(
    val traceId: String,
    val expiresAtEpochMs: Long,
)
@Serializable
data class RecentExitSignal(
    val at: kotlinx.datetime.Instant,
    val reason: String,
)

@Serializable
data class UdpExecutionPrewarm(
    val pairKey: String,
    val prewarmedAt: kotlinx.datetime.Instant,
)

@Serializable
data class LeadLagClassStats(
    val lastUpdate: kotlinx.datetime.Instant,
    val averageLagMs: Long,
    val confidenceScore: Double,
)
