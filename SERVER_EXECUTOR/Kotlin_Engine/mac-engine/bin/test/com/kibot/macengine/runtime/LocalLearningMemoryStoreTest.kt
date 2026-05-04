package com.kibot.macengine.runtime

import com.kibot.shared.models.PairId
import kotlinx.datetime.Instant
import org.junit.jupiter.api.Test
import java.nio.file.Files
import kotlin.test.assertContains
import kotlin.test.assertTrue

class LocalLearningMemoryStoreTest {

    @Test
    fun `three recent aggressive losses blacklist the pair`() {
        val store = LocalLearningMemoryStore(Files.createTempFile("learning-memory", ".json"))
        val now = Instant.parse("2026-04-09T10:00:00Z")
        repeat(3) { index ->
            store.recordTrade(
                LearningTradeEvent(
                    timestampUtc = Instant.fromEpochMilliseconds(now.toEpochMilliseconds() + (index * 60_000L)).toString(),
                    pairId = "pepe_idr",
                    bucketType = "AGGRESSIVE",
                    orderType = "MARKET",
                    entryExpectedPrice = 100.0,
                    entryRealizedPrice = 101.0,
                    exitExpectedPrice = 98.0,
                    exitRealizedPrice = 97.0,
                    entrySlippagePct = 1.0,
                    exitSlippagePct = 0.8,
                    netProfitPct = -2.2,
                    holdMinutes = 6.0,
                    exitReason = "cut_loss",
                ),
            )
        }

        val snapshot = store.snapshot(now, dailyPnlPct = -1.4, holdings = emptyList())
        assertContains(snapshot.temporaryBlacklistPairs, "pepe_idr")
    }

    @Test
    fun `high lead lag delay forces market routing for trusted pair`() {
        val store = LocalLearningMemoryStore(Files.createTempFile("learning-memory", ".json"))
        val now = Instant.parse("2026-04-09T10:00:00Z")
        store.recordLeadLagObservation("doge_idr", now, 3100L)
        store.recordLeadLagObservation("doge_idr", Instant.fromEpochMilliseconds(now.toEpochMilliseconds() + 90_000L), 3400L)

        val snapshot = store.snapshot(now, dailyPnlPct = 1.2, holdings = emptyList())
        assertContains(snapshot.forceMarketPairs, "doge_idr")
    }

    @Test
    fun `high slippage forces limit routing`() {
        val store = LocalLearningMemoryStore(Files.createTempFile("learning-memory", ".json"))
        val now = Instant.parse("2026-04-09T10:00:00Z")
        repeat(2) { index ->
            store.recordTrade(
                LearningTradeEvent(
                    timestampUtc = Instant.fromEpochMilliseconds(now.toEpochMilliseconds() + (index * 120_000L)).toString(),
                    pairId = "fartcoin_idr",
                    bucketType = "AGGRESSIVE",
                    orderType = "MARKET",
                    entryExpectedPrice = 100.0,
                    entryRealizedPrice = 101.4,
                    exitExpectedPrice = 104.0,
                    exitRealizedPrice = 103.0,
                    entrySlippagePct = 1.4,
                    exitSlippagePct = 0.95,
                    netProfitPct = 0.8,
                    holdMinutes = 8.0,
                    exitReason = "take_profit",
                ),
            )
        }

        val snapshot = store.snapshot(now, dailyPnlPct = 0.4, holdings = emptyList())
        assertContains(snapshot.forceLimitPairs, "fartcoin_idr")
    }

    @Test
    fun `autonomous review consumes learning snapshot to brake aggression`() {
        val output = AutonomousAiReviewBuilder.build(
            input = AutonomousAiReviewInput(
                now = Instant.parse("2026-04-09T10:00:00Z"),
                botId = "KiBot",
                topCandidate = PairId("doge_idr"),
                marketRegime = com.kibot.shared.models.MarketRegime.HIGH_VOLATILITY_MOMENTUM,
                freeIdr = 80_000.0,
                dailyPnlPct = -2.4,
                holdings = emptyList(),
                aiHints = emptyList(),
                aiUsedNetwork = false,
                aiBlockedReason = "failure_cooldown",
                recentTrades = emptyList(),
                learningSnapshot = LocalLearningSnapshot(
                    temporaryBlacklistPairs = listOf("pepe_idr"),
                    forceLimitPairs = listOf("fartcoin_idr"),
                    hourlyAggressionMultiplier = 0.72,
                    dailyAggressionBias = -0.14,
                    notes = listOf("hourly throttle active"),
                ),
            ),
            adaptivePolicyPath = "/tmp/adaptive_policy.json",
        )

        assertContains(output.policy.execution.temporaryBlacklistPairs, "pepe_idr")
        assertContains(output.policy.execution.forceLimitPairs, "fartcoin_idr")
        assertTrue(output.policy.adjustments.budgetBoostMultiplierDelta < 0.0)
    }

    @Test
    fun `monte carlo risk snapshot brakes aggression under clustered losses`() {
        val store = LocalLearningMemoryStore(Files.createTempFile("learning-memory", ".json"))
        val now = Instant.parse("2026-04-09T10:00:00Z")
        listOf(-3.5, -2.4, -1.8, -4.1, 0.6, -2.9, -1.2, 0.4).forEachIndexed { index, pnl ->
            store.recordTrade(
                LearningTradeEvent(
                    timestampUtc = Instant.fromEpochMilliseconds(now.toEpochMilliseconds() + (index * 60_000L)).toString(),
                    pairId = "doge_idr",
                    bucketType = "AGGRESSIVE",
                    orderType = "MARKET",
                    entryExpectedPrice = 100.0,
                    entryRealizedPrice = 100.8,
                    exitExpectedPrice = 99.0,
                    exitRealizedPrice = 98.6,
                    entrySlippagePct = 0.8,
                    exitSlippagePct = 0.6,
                    netProfitPct = pnl,
                    holdMinutes = 9.0,
                    exitReason = "risk_test",
                ),
            )
        }

        val snapshot = store.snapshot(now, dailyPnlPct = -2.7, holdings = emptyList())
        assertTrue(snapshot.risk.bootstrapConditionalVar95Pct < 0.0)
        assertTrue(snapshot.risk.ruinProbability >= 0.0)
        assertTrue(snapshot.hourlyAggressionMultiplier <= 0.78)
    }

    @Test
    fun `repeated entry rejections reduce trust and blacklist pair`() {
        val store = LocalLearningMemoryStore(Files.createTempFile("learning-memory", ".json"))
        val now = Instant.parse("2026-04-09T10:00:00Z")
        repeat(4) { index ->
            store.recordEntryRejection(
                now = Instant.fromEpochMilliseconds(now.toEpochMilliseconds() + (index * 30_000L)),
                pairId = "pepe_idr",
                reason = "learning_policy_blocked_entry",
            )
        }

        val snapshot = store.snapshot(now, dailyPnlPct = 0.2, holdings = emptyList())
        assertContains(snapshot.temporaryBlacklistPairs, "pepe_idr")
        assertTrue((snapshot.pairTrustScores["pepe_idr"] ?: 1.0) < 0.8)
    }
}
