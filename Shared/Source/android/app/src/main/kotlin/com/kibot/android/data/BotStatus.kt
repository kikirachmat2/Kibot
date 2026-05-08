package com.kibot.android.data

import kotlinx.serialization.Serializable

// ============== WebSocket Message Types ==============

@Serializable
data class WebSocketMessage(
    val type: String,
    val data: String? = null // JSON string of the actual data
)

@Serializable
data class SubscribeMessage(
    val type: String = "subscribe",
    val channels: List<String> = listOf("state", "trades", "heartbeat")
)

// ============== State Data ==============

@Serializable
data class StateData(
    val balance: Double = 0.0,
    val totalReturn: Double = 0.0,
    val pnlToday: Double = 0.0,
    val positions: List<Position> = emptyList(),
    val netWorthHistory: List<NetWorthPoint> = emptyList(),
    val whatIfSimulation: SimulationSummary? = null,
)

@Serializable
data class Position(
    val pair: String,
    val amount: Double,
    val buyPrice: Double,
    val currentPrice: Double,
    val pnl: Double,
    val pnlPercent: Double,
    val valueIdr: Double = 0.0,
)

@Serializable
data class NetWorthPoint(
    val timestamp: Long,
    val value: Double
)

@Serializable
data class SimulationSummary(
    val runAt: String,
    val pairsSimulated: Int,
    val topOpportunities: List<String> = emptyList(),
    val results: Map<String, SimulationResult> = emptyMap()
)

@Serializable
data class SimulationResult(
    val pair: String,
    val currentPrice: Double,
    val winProbability: Double,
    val expectedValue: Double,
    val riskRewardRatio: Double,
    val kellySizeRecommended: Double,
    val verdict: String
)

@Serializable
data class TradeHistorySummary(
    val lastUpdated: String = "",
    val today: TradePeriodStats = TradePeriodStats(),
    val last7Days: TradePeriodStats = TradePeriodStats(),
    val last30Days: TradePeriodStats = TradePeriodStats()
)

@Serializable
data class TradePeriodStats(
    val count: Int = 0,
    val winCount: Int = 0,
    val lossCount: Int = 0,
    val totalNetPnlPct: Double = 0.0,
    val totalNetPnlIdr: Double = 0.0,
    val totalFeeIdr: Double = 0.0,
    val marketOrderCount: Int = 0,
    val avgHoldingMs: Long = 0L,
    val topLosers: List<TradeLoser> = emptyList()
)

@Serializable
data class TradeLoser(
    val pair: String,
    val pnl: Double,
    val reason: String
)

// ============== Heartbeat Data ==============

@Serializable
data class HeartbeatData(
    val KiBot: ServiceStatus = ServiceStatus(),
    val kibot: ServiceStatus = ServiceStatus()
)

@Serializable
data class ServiceStatus(
    val status: String = "offline", // "online", "degraded", "offline"
    val ping: Long = 0,
    val aiStatus: String = "idle", // "active", "idle"
    val enabled: Boolean = true,
    val holdings: List<Holding> = emptyList()
)

@Serializable
data class Holding(
    val coin: String,
    val amount: Double,
    val price: Double,
    val pnl: Double
)

// ============== Trade Data ==============

@Serializable
data class TradeData(
    val id: String,
    val pair: String,
    val side: String, // "buy" or "sell"
    val status: String = "",
    val orderType: String = "",
    val price: Double,
    val amount: Double,
    val total: Double,
    val timestamp: Long,
    val entryPrice: Double? = null,
    val exitPrice: Double? = null,
    val profitLoss: Double? = null,
    val profitLossPercent: Double? = null,
)

// ============== Portfolio Data ==============

@Serializable
data class ReturnSummary(
    val day1: Double = 0.0,
    val day7: Double = 0.0,
    val day30: Double = 0.0,
    val day1Idr: Double = 0.0,
    val day7Idr: Double = 0.0,
    val day30Idr: Double = 0.0,
)

@Serializable
data class AssetAllocation(
    val coin: String,
    val percentage: Double,
    val value: Double
)

// ============== UI State Classes ==============

data class BotState(
    val balance: Double = 0.0,
    val totalReturn: Double = 0.0,
    val pnlToday: Double = 0.0,
    val pnlTodayPercent: Double = 0.0,
    val positions: List<Position> = emptyList(),
    val netWorthHistory: List<NetWorthPoint> = emptyList(),
    val returnSummary: ReturnSummary = ReturnSummary(),
    val assetAllocation: List<AssetAllocation> = emptyList(),
    val trades: List<TradeData> = emptyList(),
    val topCandidate: String = "-",
    val radarPairs: List<String> = emptyList(),
    val heartbeat: HeartbeatData = HeartbeatData(),
    val effectiveState: String = "STOPPED",
    val syncHealth: String = "DEGRADED",
    val aiProviderSummary: String = "AI summary belum siap.",
    val healthSummary: String = "Menunggu snapshot server.",
    val statusMessage: String = "Server monitor sedang booting.",
    val lastActivityUpdate: Long = 0,  // Timestamp for last activity update
    val connectedBotId: String = "unknown",
    val isConnected: Boolean = false,
    val lastUpdate: Long = 0,
    val whatIfSimulation: SimulationSummary? = null,
    val tradeHistory: TradeHistorySummary? = null,
)

enum class ConnectionStatus {
    CONNECTED, CONNECTING, DISCONNECTED, ERROR
}

// ============== Legacy Compatibility ==============

data class BotStatus(
    val balance: Balance,
    val pnl: PnL,
    val capitalSplit: CapitalSplit,
    val activeTrades: List<Trade>,
    val status: String,
    val timestamp: Long
)

data class Balance(
    val idr: Double,
    val usdt: Double,
    val total: Double
)

data class PnL(
    val daily: Double,
    val percentage: Double,
    val trend: List<Double>
)

data class CapitalSplit(
    val highConviction: Double,
    val aggressive: Double
)

data class Trade(
    val pair: String,
    val entry: Double,
    val current: Double,
    val profit: Double,
    val profitPct: Double
)

// Configuration model
data class ServerConfig(
    val host: String = DEFAULT_HOST,
    val port: Int = DEFAULT_PORT,
    val dashboardAuthToken: String = "",
) {
    companion object {
        const val DEFAULT_HOST = "168.110.201.228"
        const val DEFAULT_PORT = 8787
        const val TUNNEL_HOST = "127.0.0.1"
        const val PROXY_TUNNEL_PORT = 18787
        const val DIRECT_TUNNEL_PORT = 18798

        fun buildUrl(host: String, port: Int, dashboardAuthToken: String): String {
            val base = "ws://$host:$port/ws"
            val token = dashboardAuthToken.trim()
            if (token.isBlank()) return base
            val encoded = java.net.URLEncoder.encode(token, "UTF-8")
            return "$base?token=$encoded"
        }
    }

    fun getUrl(): String {
        return buildUrl(host, port, dashboardAuthToken)
    }

    fun getTunnelUrl(): String {
        return buildUrl(TUNNEL_HOST, PROXY_TUNNEL_PORT, dashboardAuthToken)
    }

    fun getDirectTunnelUrl(): String {
        return buildUrl(TUNNEL_HOST, DIRECT_TUNNEL_PORT, dashboardAuthToken)
    }

    fun getConnectionUrls(): List<String> {
        return listOf(getTunnelUrl(), getDirectTunnelUrl(), getUrl()).distinct()
    }
}
