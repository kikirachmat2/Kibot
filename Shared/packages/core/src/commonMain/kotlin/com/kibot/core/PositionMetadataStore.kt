package com.kibot.core

import java.util.concurrent.ConcurrentHashMap
import com.kibot.shared.models.HyperTargetKind
import kotlinx.datetime.Instant
import kotlin.collections.ArrayDeque

/**
 * Centralized store for position-specific metadata and tracking state.
 */
class PositionMetadataStore {
    val hyperAggressivePeakBidByPair = ConcurrentHashMap<String, Double>()
    val hyperAggressiveEntryReasonByPair = ConcurrentHashMap<String, HyperTargetKind>()
    val partialTakeProfitExecutedByPair = ConcurrentHashMap<String, Boolean>()
    val positionBucketTypeByPair = ConcurrentHashMap<String, String>()
    
    // Hyper-aggressive pulse tracking
    val hyperAggressivePulseByPair = ConcurrentHashMap<String, ArrayDeque<PairMicroPulseSample>>()
    
    // Trailing state for various strategies
    val leadLagTrailingPeakBidByPair = ConcurrentHashMap<String, Double>()
    val localAutonomyPeakBidByPair = ConcurrentHashMap<String, Double>()
    
    // Entry/Exit timing
    val leadLagEntrySubmittedAtByPair = ConcurrentHashMap<String, Instant>()
    val barbarianLeadLagEntryAtByPair = ConcurrentHashMap<String, Instant>()
    val localAutonomyTrailingFloorByPair = ConcurrentHashMap<String, LocalTrailingSnapshot>()
    val localAutonomyTrailingFloorLogByPair = ConcurrentHashMap<String, Double>()
    val hyperAggressiveTrackedEntryAtByPair = ConcurrentHashMap<String, Instant>()
    val forcedSellTraceByPair = ConcurrentHashMap<String, ForcedSellSignal>()
    
    // Risk & Execution State
    val positionEntryCapitalByPair = ConcurrentHashMap<String, Double>()
    val sinBinUntilByPair = ConcurrentHashMap<String, Instant>()
    val dustQuarantinePairs = ConcurrentHashMap.newKeySet<String>()
    val emergencyWarningCooldownByPair = ConcurrentHashMap<String, Instant>()
    val recentExitSignalByPair = ConcurrentHashMap<String, RecentExitSignal>()
    val perSymbolExecutionLeaseUntilByPair = ConcurrentHashMap<String, Instant>()
    val udpExecutionPrewarmByPair = ConcurrentHashMap<String, UdpExecutionPrewarm>()
    
    // Lead-Lag State
    val leadLagSentAtByPair = ConcurrentHashMap<String, Instant>()
    val leadLagOriginSentAtByPair = ConcurrentHashMap<String, Long>()
    val leadLagReceivedAtByPair = ConcurrentHashMap<String, Instant>()
    val leadLagTraceByPair = ConcurrentHashMap<String, String>()
    val leadLagDetectedAtByPair = ConcurrentHashMap<String, Long>()
    val leadLagStatsByClass = ConcurrentHashMap<com.kibot.shared.models.CoinClass, LeadLagClassStats>()
    val leadLagMicroPulseByPair = ConcurrentHashMap<String, ArrayDeque<PairMicroPulseSample>>()
    val leadLagGradualPulseByPair = ConcurrentHashMap<String, ArrayDeque<PairMicroPulseSample>>()

    fun clear() {
        hyperAggressivePeakBidByPair.clear()
        hyperAggressiveEntryReasonByPair.clear()
        partialTakeProfitExecutedByPair.clear()
        positionBucketTypeByPair.clear()
        hyperAggressivePulseByPair.clear()
        leadLagTrailingPeakBidByPair.clear()
        localAutonomyPeakBidByPair.clear()
        leadLagEntrySubmittedAtByPair.clear()
        barbarianLeadLagEntryAtByPair.clear()
        localAutonomyTrailingFloorByPair.clear()
        localAutonomyTrailingFloorLogByPair.clear()
        hyperAggressiveTrackedEntryAtByPair.clear()
        forcedSellTraceByPair.clear()
        positionEntryCapitalByPair.clear()
        sinBinUntilByPair.clear()
        dustQuarantinePairs.clear()
        emergencyWarningCooldownByPair.clear()
        recentExitSignalByPair.clear()
        perSymbolExecutionLeaseUntilByPair.clear()
        udpExecutionPrewarmByPair.clear()
        leadLagSentAtByPair.clear()
        leadLagOriginSentAtByPair.clear()
        leadLagReceivedAtByPair.clear()
        leadLagTraceByPair.clear()
        leadLagDetectedAtByPair.clear()
        leadLagStatsByClass.clear()
        leadLagMicroPulseByPair.clear()
        leadLagGradualPulseByPair.clear()
    }
}
