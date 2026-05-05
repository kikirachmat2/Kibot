package com.kibot.shared.models

import kotlinx.datetime.Instant
import kotlinx.serialization.Serializable

@Serializable
data class CommandCenterLiveSnapshot(
    val serverId: String,
    val serverLabel: String,
    val botId: BotId,
    val effectiveState: BotEffectiveState,
    val syncHealth: SyncHealth,
    val liveExecutionEnabled: Boolean,
    val operatingMode: BotMode,
    val edgeConfidence: EdgeConfidence,
    val marketRegime: MarketRegime,
    val aiProviderSummary: String,
    val upstreamMarker: String = "",
    val activeEngine: String,
    val standbyEngine: String,
    val topCandidate: String,
    val scanUniverseCount: Int,
    val leaseTerm: Long,
    val healthSummary: String,
    val lastRejectedReason: String = "",
    val statusMessage: String,
    val lastHeartbeatLabel: String,
    val lastUpdatedLabel: String,
    val totalValueIdr: String,
    val portfolioValueIdr: String,
    val freeIdrLabel: String,
    val referenceQuoteAssetPriceIdr: Double? = null,
    val pnlTodayIdr: String,
    val pnlTodayPctLabel: String,
    val totalReturnIdr: String = "",
    val totalReturnPctLabel: String = "",
    val cumulativeReturnPctLabel: String = "",
    val return7dIdr: String,
    val return7dPctLabel: String,
    val return30dIdr: String,
    val return30dPctLabel: String,
    val exchangePingMs: String,
    val exchangePingValueMs: Long? = null,
    val KiBotPingMs: Long? = null,
    val KiBotNodeStatus: String? = null,
    val kibotNodeStatus: String? = null,
    val serverUptime: String,
    val releaseLabel: String,
    val targetPursuitLabel: String,
    val radarPairs: List<String> = emptyList(),
    val holdingsDetailed: List<CommandCenterHolding> = emptyList(),
    val recentOrders: List<CommandCenterOrder> = emptyList(),
    val liveTimeline: List<CommandCenterTimelineEntry> = emptyList(),
    val netWorthHistory: List<CommandCenterNetWorthPoint> = emptyList(),
    val assetAllocationDetailed: List<CommandCenterAssetAllocation> = emptyList(),
    val whatIfSimulation: CommandCenterSimulationSummary? = null,
    val updatedAtEpochMs: Long,
)

@Serializable
data class CommandCenterSimulationSummary(
    val runAt: String,
    val pairsSimulated: Int,
    val topOpportunities: List<String> = emptyList(),
    val results: Map<String, CommandCenterSimulationResult> = emptyMap(),
)

@Serializable
data class CommandCenterSimulationResult(
    val pair: String,
    val currentPrice: Double,
    val winProbability: Double,
    val expectedValue: Double,
    val riskRewardRatio: Double,
    val kellySizeRecommended: Double,
    val verdict: String,
)

@Serializable
data class CommandCenterHolding(
    val assetCode: String,
    val assetLabel: String,
    val quantityLabel: String,
    val valueIdrLabel: String,
    val entryPriceLabel: String = "",
    val currentPriceLabel: String = "",
    val pnlIdrLabel: String = "",
    val pnlPctLabel: String = "",
)

@Serializable
data class CommandCenterOrder(
    val timestampEpochMs: Long,
    val pair: String,
    val side: String,
    val status: String,
    val orderType: String = "",
    val detail: String,
    val entryPriceLabel: String = "",
    val exitPriceLabel: String = "",
    val outcomeLabel: String = "",
    val pnlIdrLabel: String = "",
    val pnlPctLabel: String = "",
)

@Serializable
data class CommandCenterTimelineEntry(
    val timestampEpochMs: Long,
    val category: String,
    val message: String,
)

@Serializable
data class CommandCenterNetWorthPoint(
    val timestamp: Long,
    val value: String,
)

@Serializable
data class CommandCenterAssetAllocation(
    val coin: String,
    val percentageLabel: String,
    val valueLabel: String,
)

@Serializable
data class CommandCenterCommandRequest(
    val command: String,
    val argument: String? = null,
    val idempotencyKey: String? = null,
    val issuedAtEpochMs: Long = 0L,
)

@Serializable
data class CommandCenterCommandReply(
    val accepted: Boolean,
    val message: String,
    val echoCommand: String? = null,
    val updatedSnapshot: CommandCenterLiveSnapshot? = null,
    val issuedAtEpochMs: Long = 0L,
)

@Serializable
sealed class CommandCenterWsEnvelope {
    @Serializable
    data class Snapshot(val snapshot: CommandCenterLiveSnapshot) : CommandCenterWsEnvelope()

    @Serializable
    data class Reply(val reply: CommandCenterCommandReply) : CommandCenterWsEnvelope()

    @Serializable
    data class Ping(val issuedAtEpochMs: Long, val serverTimeEpochMs: Long) : CommandCenterWsEnvelope()
}
