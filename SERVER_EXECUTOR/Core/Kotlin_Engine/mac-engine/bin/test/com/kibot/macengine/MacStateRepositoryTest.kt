package com.kibot.macengine

import com.kibot.macengine.state.MacCommand
import com.kibot.macengine.state.MacDashboardState
import com.kibot.macengine.state.MacHoldingDetail
import com.kibot.macengine.state.MacStateRepository
import com.kibot.shared.models.BotEffectiveState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class MacStateRepositoryTest {
    @Test
    fun `status note updates repository message`() {
        val repository = MacStateRepository()
        repository.applyAndReturn(MacCommand.START_BOT)
        assertTrue(repository.state.value.statusMessage.contains("start", ignoreCase = true))
    }

    @Test
    fun `runtime state replaces dashboard snapshot`() {
        val repository = MacStateRepository()
        repository.applyRuntimeState(
            MacDashboardState(
                isBotRunning = true,
                effectiveState = BotEffectiveState.RUNNING,
                operatingMode = "GROWTH",
                edgeConfidence = "HIGH",
                marketRegime = "HEALTHY_UPTREND",
                topCandidate = "btc_idr",
                radarPairs = listOf("btc_idr", "eth_idr"),
                scanUniverseCount = 120,
                releaseLabel = "#99",
                liveExecutionEnabled = false,
                portfolioValueIdr = "Rp100.000",
                freeIdrLabel = "Rp20.000",
                totalValueIdr = "Rp100.000",
                pnlTodayIdr = "+Rp2.500",
                pnlTodayPctLabel = "+2.5%",
                return7dIdr = "+Rp5.000",
                return7dPctLabel = "+5.0%",
                return30dIdr = "+Rp12.000",
                return30dPctLabel = "+12.0%",
                targetPursuitLabel = "CHASE",
                aiProviderSummary = "AI sehat: openrouter",
                syncPathLabel = "Supabase + LAN",
                activeEngine = "MacBook Pro",
                standbyEngine = "Android Poco M3",
                syncHealth = "HEALTHY",
                leaseTerm = 11,
                healthSummary = "Master healthy.",
                weeklyLearningSummary = "Belum ada review mingguan.",
                weeklyAdaptationSummary = "Adaptasi mingguan belum tersedia.",
                lastHeartbeatLabel = "2s ago",
                lastUpdatedLabel = "08:15 WIB",
                statusMessage = "Mac currently holds the master lease.",
                lastUpdatedEpochMs = 1L,
                serverLocation = "Oracle Cloud Singapore",
                serverUptime = "02h 15m",
                heldAssets = listOf("DOGE", "TRX"),
                holdingsDetailed = listOf(
                    MacHoldingDetail(
                        assetCode = "DOGE",
                        assetLabel = "Doge",
                        quantityLabel = "10 DOGE",
                        valueIdrLabel = "Rp12.000",
                        entryPriceLabel = "Rp1.080",
                        currentPriceLabel = "Rp1.200",
                        pnlIdrLabel = "+Rp1.200",
                        pnlPctLabel = "+10.0%",
                    ),
                ),
                exchangePingMs = "84",
                KiBotNodeStatus = "online",
                kibotNodeStatus = "online",
                KiBotNodeStatus = "online",
                liveTimeline = emptyList(),
                recentOrders = emptyList(),
                trailingFloors = emptyList(),
            ),
        )

        assertTrue(repository.state.value.isBotRunning)
        assertEquals("MacBook Pro", repository.state.value.activeEngine)
    }

    @Test
    fun `runtime state keeps previous IDR portfolio during degraded quote gap`() {
        val repository = MacStateRepository()
        repository.applyRuntimeState(
            dashboardState(
                isBotRunning = true,
                effectiveState = BotEffectiveState.RUNNING,
                edgeConfidence = "HIGH",
                marketRegime = "HEALTHY_UPTREND",
                topCandidate = "req_idr",
                radarPairs = listOf("req_idr"),
                scanUniverseCount = 80,
                liveExecutionEnabled = true,
                portfolioValueIdr = "Rp1.200",
                freeIdrLabel = "Rp300",
                totalValueIdr = "Rp1.200",
                holdingsDetailed = listOf(
                    MacHoldingDetail(
                        assetCode = "REQ",
                        assetLabel = "REQ",
                        quantityLabel = "1 REQ",
                        valueIdrLabel = "Rp1.200",
                        entryPriceLabel = "Rp1.100",
                        currentPriceLabel = "Rp1.200",
                        pnlIdrLabel = "+Rp100",
                        pnlPctLabel = "+9.0%",
                    ),
                ),
                syncHealth = "HEALTHY",
                exchangePingMs = "35",
                lastUpdatedEpochMs = 10L,
            ),
        )

        repository.applyRuntimeState(
            dashboardState(
                isBotRunning = true,
                effectiveState = BotEffectiveState.DEGRADED,
                edgeConfidence = "MEDIUM",
                marketRegime = "SIDEWAYS",
                topCandidate = "-",
                radarPairs = emptyList(),
                scanUniverseCount = 0,
                liveExecutionEnabled = true,
                portfolioValueIdr = "Rp900",
                freeIdrLabel = "Rp0",
                totalValueIdr = "Rp900",
                holdingsDetailed = emptyList(),
                syncHealth = "DEGRADED",
                exchangePingMs = "--",
                statusMessage = "sync failed while quote feed recovers",
                lastUpdatedEpochMs = 20L,
            ),
        )

        assertEquals("Rp1.200", repository.state.value.portfolioValueIdr)
        assertEquals("Rp1.200", repository.state.value.totalValueIdr)
    }

    private fun dashboardState(
        isBotRunning: Boolean,
        effectiveState: BotEffectiveState,
        edgeConfidence: String,
        marketRegime: String,
        topCandidate: String,
        radarPairs: List<String>,
        scanUniverseCount: Int,
        liveExecutionEnabled: Boolean,
        portfolioValueIdr: String,
        freeIdrLabel: String,
        totalValueIdr: String,
        holdingsDetailed: List<MacHoldingDetail>,
        syncHealth: String,
        exchangePingMs: String,
        lastUpdatedEpochMs: Long,
        statusMessage: String = "Runtime snapshot applied.",
    ): MacDashboardState = MacDashboardState(
        isBotRunning = isBotRunning,
        effectiveState = effectiveState,
        operatingMode = "GROWTH",
        edgeConfidence = edgeConfidence,
        marketRegime = marketRegime,
        topCandidate = topCandidate,
        radarPairs = radarPairs,
        scanUniverseCount = scanUniverseCount,
        releaseLabel = "#test",
        liveExecutionEnabled = liveExecutionEnabled,
        portfolioValueIdr = portfolioValueIdr,
        freeIdrLabel = freeIdrLabel,
        totalValueIdr = totalValueIdr,
        pnlTodayIdr = "+Rp0",
        pnlTodayPctLabel = "+0.0%",
        return7dIdr = "+Rp0",
        return7dPctLabel = "+0.0%",
        return30dIdr = "+Rp0",
        return30dPctLabel = "+0.0%",
        targetPursuitLabel = "HOLD",
        aiProviderSummary = "AI sehat",
        syncPathLabel = "Supabase + LAN",
        activeEngine = "MacBook Pro",
        standbyEngine = "Android Poco M3",
        syncHealth = syncHealth,
        leaseTerm = 1,
        healthSummary = "Monitoring runtime.",
        weeklyLearningSummary = "Belum ada review mingguan.",
        weeklyAdaptationSummary = "Belum ada adaptasi mingguan.",
        lastHeartbeatLabel = "baru saja",
        lastUpdatedLabel = "08:15 WIB",
        statusMessage = statusMessage,
        lastUpdatedEpochMs = lastUpdatedEpochMs,
        serverLocation = "Oracle Cloud Singapore",
        serverUptime = "00h 10m",
        heldAssets = holdingsDetailed.map { it.assetCode },
        holdingsDetailed = holdingsDetailed,
        exchangePingMs = exchangePingMs,
        KiBotNodeStatus = "online",
        kibotNodeStatus = "online",
        KiBotNodeStatus = "online",
        liveTimeline = emptyList(),
        recentOrders = emptyList(),
        trailingFloors = emptyList(),
    )
}
