package com.kibot.core

import com.kibot.shared.models.AuditLogRecord
import com.kibot.shared.models.BotUpdateRecommendation
import com.kibot.shared.models.BotDesiredState
import com.kibot.shared.models.BotId
import com.kibot.shared.models.CommandEnvelope
import com.kibot.shared.models.CommandId
import com.kibot.shared.models.CommandStatus
import com.kibot.shared.models.CommandType
import com.kibot.shared.models.DailyEquityHistoryPoint
import com.kibot.shared.models.DailyRiskSnapshot
import com.kibot.shared.models.DeviceDescriptor
import com.kibot.shared.models.DeviceId
import com.kibot.shared.models.DevicePlatform
import com.kibot.shared.models.DeviceRole
import com.kibot.shared.models.EncryptedCredentialBundle
import com.kibot.shared.models.EngineHeartbeatSnapshot
import com.kibot.shared.models.EngineLeaseSnapshot
import com.kibot.shared.models.ExecutionActionId
import com.kibot.shared.models.ExecutionActionTicket
import com.kibot.shared.models.OrderSnapshot
import com.kibot.shared.models.PairScore
import com.kibot.shared.models.PositionSnapshot
import com.kibot.shared.models.RuntimeIntelligenceUpdate
import com.kibot.shared.models.WeeklyLearningSummary
import kotlinx.datetime.LocalDate
import kotlinx.datetime.Instant

data class KingDashboardSnapshot(
    val totalBalanceIdr: Double,
    val currentPingMs: Long?,
    val activeLivePairs: List<String>,
    val latestManagerLog: String?,
    val udpPingMs: Long? = null,
    val KiBotPingMs: Long? = null,
    val targetProgressPct: Double? = null,
    val KiBotBalanceIdr: Double? = null,
    val KiBotPnlTodayPct: Double? = null,
    val KiBotPairActive: String? = null,
)

data class TradeHistoryRecord(
    val pair: String,
    val side: String,
    val status: String,
    val detail: String,
    val createdAt: Instant? = null,
)

data class TradeLogSubmission(
    val tradeId: String,
    val pairId: String,
    val category: String,
    val entryPrice: Double,
    val exitPrice: Double,
    val budgetIdr: Double,
    val pnlIdr: Double,
    val pnlPct: Double,
    val orderTypeEntry: String,
    val orderTypeExit: String,
    val pumpPhase: String,
    val pumpScore: Double,
    val holdMinutes: Long,
    val win: Boolean,
    val exitReason: String,
    val bucketType: String,
    val entryAt: Instant,
    val exitAt: Instant,
)

data class DeviceRegistration(
    val deviceId: DeviceId,
    val displayName: String,
    val platform: DevicePlatform,
    val role: DeviceRole,
)

interface ControlPlaneGateway {
    suspend fun registerDevice(registration: DeviceRegistration): DeviceDescriptor

    suspend fun fetchBotState(botId: BotId): com.kibot.shared.models.BotStateSnapshot?

    suspend fun fetchLease(botId: BotId): EngineLeaseSnapshot?

    suspend fun fetchDevices(botId: BotId): List<DeviceDescriptor>

    suspend fun fetchDailyRisk(botId: BotId, date: LocalDate): DailyRiskSnapshot?

    suspend fun fetchDailyRiskHistory(botId: BotId, days: Int = 7): List<DailyEquityHistoryPoint>

    suspend fun upsertDailyRisk(
        botId: BotId,
        date: LocalDate,
        snapshot: DailyRiskSnapshot,
    )

    suspend fun fetchPendingCommands(botId: BotId, deviceId: DeviceId, limit: Int = 25): List<CommandEnvelope>

    suspend fun setDesiredState(botId: BotId, desiredState: BotDesiredState)

    suspend fun acquireLease(botId: BotId, deviceId: DeviceId, ttlSeconds: Int): EngineLeaseSnapshot

    suspend fun releaseLease(
        botId: BotId,
        deviceId: DeviceId,
        term: Long,
        reason: String? = null,
    ): EngineLeaseSnapshot

    suspend fun appendHeartbeat(snapshot: EngineHeartbeatSnapshot)

    suspend fun publishRuntimeIntelligence(update: RuntimeIntelligenceUpdate)

    suspend fun appendStrategyMetrics(botId: BotId, metrics: List<PairScore>)

    suspend fun upsertWeeklyLearningSummary(summary: WeeklyLearningSummary)

    suspend fun fetchLatestWeeklyLearningSummary(botId: BotId): WeeklyLearningSummary?

    suspend fun upsertUpdateRecommendation(recommendation: BotUpdateRecommendation)

    suspend fun fetchLatestUpdateRecommendations(botId: BotId, limit: Int = 10): List<BotUpdateRecommendation>

    suspend fun enqueueCommand(
        botId: BotId,
        createdBy: DeviceId,
        commandType: CommandType,
        targetDeviceId: DeviceId? = null,
        payloadJson: String? = null,
    ): CommandEnvelope

    suspend fun updateCommandStatus(commandId: CommandId, status: CommandStatus)

    suspend fun reserveExecutionAction(
        botId: BotId,
        deviceId: DeviceId,
        term: Long,
        orderIntentId: String,
        actionType: String,
    ): ExecutionActionTicket

    suspend fun completeExecutionAction(
        actionId: ExecutionActionId,
        deviceId: DeviceId,
        status: String,
    )

    suspend fun markConflictSafeMode(botId: BotId, reason: String)

    suspend fun appendLog(botId: BotId, record: AuditLogRecord)

    suspend fun upsertKingDashboardFastTelemetry(
        totalBalanceIdr: Double,
        currentPingMs: Long?,
        activeLivePairs: List<String>,
    )

    suspend fun fetchKingDashboardSnapshot(): KingDashboardSnapshot?

    suspend fun fetchTradeHistory(limit: Int = 50, offset: Int = 0): List<TradeHistoryRecord>

    suspend fun submitTradeLog(record: TradeLogSubmission)

    suspend fun fetchRecentLogs(botId: BotId, limit: Int = 50): List<AuditLogRecord>

    suspend fun fetchRecentOrders(botId: BotId, limit: Int = 50): List<OrderSnapshot>

    suspend fun fetchOpenPersistedOrders(botId: BotId): List<OrderSnapshot>

    suspend fun fetchActivePositions(botId: BotId): List<PositionSnapshot>

    suspend fun upsertOrderSnapshot(
        botId: BotId,
        term: Long,
        deviceId: DeviceId,
        order: OrderSnapshot,
    )

    suspend fun upsertEncryptedCredentialBundle(bundle: EncryptedCredentialBundle)

    suspend fun fetchEncryptedCredentialBundle(botId: BotId): EncryptedCredentialBundle?
    suspend fun fetchPairWhitelist(botId: BotId): List<TradeWhitelistRecord>

    suspend fun upsertPairWhitelist(botId: BotId, record: TradeWhitelistRecord)
}

data class TradeWhitelistRecord(
    val pairId: String,
    val wins: Int,
    val totalTrades: Int,
    val lastUpdated: Instant,
)
