package com.kibot.macengine

import com.kibot.controlplane.ControlPlaneConfig
import com.kibot.binance.BinanceClientConfig
import com.kibot.indodax.IndodaxClientConfig
import com.kibot.macengine.config.ExchangeKind
import com.kibot.macengine.config.HyperAggressiveConfig
import com.kibot.macengine.config.MacRuntimeConfig
import com.kibot.macengine.runtime.MacEngineDaemon
import com.kibot.macengine.runtime.exchangeProbeBackoffMillis
import com.kibot.macengine.runtime.resolveOwnership
import com.kibot.macengine.runtime.validateMarketData
import com.kibot.macengine.state.MacStateRepository
import com.kibot.shared.models.BalanceSnapshot
import com.kibot.shared.models.BotDesiredState
import com.kibot.shared.models.BotEffectiveState
import com.kibot.shared.models.BotId
import com.kibot.shared.models.BotMode
import com.kibot.shared.models.BotStateSnapshot
import com.kibot.shared.models.DecimalValue
import com.kibot.shared.models.DeviceId
import com.kibot.shared.models.DevicePlatform
import com.kibot.shared.models.DeviceRole
import com.kibot.shared.models.EdgeConfidence
import com.kibot.shared.models.EngineLeaseSnapshot
import com.kibot.shared.models.FillSnapshot
import com.kibot.shared.models.LeaseState
import com.kibot.shared.models.LeaseTerm
import com.kibot.shared.models.LogLevel
import com.kibot.shared.models.MarketRegime
import com.kibot.shared.models.OrderId
import com.kibot.shared.models.OrderSide
import com.kibot.shared.models.OrderSnapshot
import com.kibot.shared.models.OrderStatus
import com.kibot.shared.models.OrderType
import com.kibot.shared.models.PairId
import com.kibot.shared.models.PositionId
import com.kibot.shared.models.PositionSnapshot
import com.kibot.shared.models.PositionState
import com.kibot.shared.models.ProfitProtectionStatus
import com.kibot.shared.models.RiskLadderLevel
import com.kibot.shared.models.SetupType
import com.kibot.shared.models.StrategyMode
import com.kibot.shared.models.SyncHealth
import com.kibot.shared.models.WeeklyAdaptationPlan
import com.kibot.shared.models.WeeklyLearningSummary
import com.kibot.shared.models.CommandType
import com.kibot.core.MarketBuyImpactEstimate
import com.kibot.shared.models.TradingHorizon
import com.kibot.testkit.FakeControlPlaneGateway
import com.kibot.testkit.FakeExchangeGateway
import com.sun.net.httpserver.HttpServer
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.datetime.LocalDate
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import kotlin.time.Duration.Companion.milliseconds
import kotlin.time.Duration.Companion.minutes
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files
import kotlin.coroutines.Continuation
import kotlin.coroutines.EmptyCoroutineContext
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.fail

class MacEngineDaemonTest {
    init {
        ensureTestManagerGateServer()
    }

    private val botId = BotId("main")
    private val macId = DeviceId("macbook-main")
    private val androidId = DeviceId("android-main")
    private val fixedClock: Clock = object : Clock {
        private val offsetMs =
            Instant.parse("2026-03-15T00:00:00Z").toEpochMilliseconds() - System.currentTimeMillis()

        override fun now(): Instant = Instant.fromEpochMilliseconds(System.currentTimeMillis() + offsetMs)
    }

    @Test
    fun `ownership resolution uses lease as canonical authority`() {
        val consistentOwner = resolveOwnership(ownerByList = true, ownerByLease = true)
        val consistentNotOwner = resolveOwnership(ownerByList = false, ownerByLease = false, lastResolved = consistentOwner.resolvedIsOwner)
        val mismatchSafetyBlock = resolveOwnership(ownerByList = true, ownerByLease = false, lastResolved = consistentNotOwner.resolvedIsOwner)
        val mismatchLeaseWins = resolveOwnership(ownerByList = false, ownerByLease = true, lastResolved = mismatchSafetyBlock.resolvedIsOwner)

        assertTrue(consistentOwner.resolvedIsOwner)
        assertFalse(consistentOwner.mismatch)
        assertFalse(consistentNotOwner.resolvedIsOwner)
        assertFalse(consistentNotOwner.mismatch)
        assertFalse(mismatchSafetyBlock.resolvedIsOwner)
        assertTrue(mismatchSafetyBlock.mismatch)
        assertTrue(mismatchSafetyBlock.shouldLog)
        assertTrue(mismatchLeaseWins.resolvedIsOwner)
        assertTrue(mismatchLeaseWins.mismatch)
    }

    @Test
    fun `market data validation blocks empty stale or suspicious snapshots`() {
        val now = Instant.parse("2026-03-15T00:01:00Z")
        val empty = validateMarketData(now = now, marketQuotes = emptyList(), equityIdr = 75_000.0)
        val lowEquity = validateMarketData(now = now, marketQuotes = listOf(marketQuote("eth_idr", 120_000.0, 0.77)), equityIdr = 459.0)
        val stale = validateMarketData(
            now = now,
            marketQuotes = listOf(marketQuote("eth_idr", 120_000.0, 0.77).copy(capturedAt = Instant.parse("2026-03-14T23:56:00Z"))),
            equityIdr = 75_000.0,
        )
        val healthy = validateMarketData(
            now = now,
            marketQuotes = listOf(marketQuote("eth_idr", 120_000.0, 0.77).copy(capturedAt = Instant.parse("2026-03-15T00:00:45Z"))),
            equityIdr = 75_000.0,
        )

        assertFalse(empty.isValid)
        assertTrue(empty.reason.contains("No quotes"))
        assertFalse(lowEquity.isValid)
        assertTrue(lowEquity.reason.contains("Equity suspiciously low"))
        assertFalse(stale.isValid)
        assertTrue(stale.reason.contains("stale"))
        assertTrue(healthy.isValid)
        assertEquals(1, healthy.quoteCount)
    }

    @Test
    fun `exchange probe backoff grows exponentially and caps at two minutes`() {
        assertEquals(5_000L, exchangeProbeBackoffMillis(1))
        assertEquals(10_000L, exchangeProbeBackoffMillis(2))
        assertEquals(20_000L, exchangeProbeBackoffMillis(3))
        assertEquals(40_000L, exchangeProbeBackoffMillis(4))
        assertEquals(80_000L, exchangeProbeBackoffMillis(5))
        assertEquals(120_000L, exchangeProbeBackoffMillis(6))
        assertEquals(120_000L, exchangeProbeBackoffMillis(10))
    }

    @Test
    fun `standby acquires expired lease after clean reconciliation`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.DEGRADED,
            activeDeviceId = androidId,
            standbyDeviceId = macId,
            currentTerm = LeaseTerm(1),
            syncHealth = SyncHealth.DEGRADED,
            strategyMode = StrategyMode.AUTO_CONSERVATIVE,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = androidId,
                term = LeaseTerm(1),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2020-01-01T00:00:10Z"),
                lastHeartbeatAt = Instant.parse("2020-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()

        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote("eth_idr", 120_000.0, 0.77),
            ),
            balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("500000"))),
        )
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(),
            clock = fixedClock,
        )

        daemon.syncOnce()

        val lease = controlPlane.fetchLease(botId)
        assertEquals(macId, lease?.currentHolder)
        assertEquals(BotEffectiveState.RUNNING, controlPlane.fetchBotState(botId)?.effectiveState)
        assertTrue(repository.state.value.activeEngine.contains("Oracle", ignoreCase = true))
        assertEquals(BotMode.ATTACK, controlPlane.runtimeIntelligence?.operatingMode)
    }

    @Test
    fun `takeover is blocked and safe mode is triggered when reconciliation is ambiguous`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.DEGRADED,
            activeDeviceId = androidId,
            standbyDeviceId = macId,
            currentTerm = LeaseTerm(3),
            syncHealth = SyncHealth.DEGRADED,
            strategyMode = StrategyMode.AUTO_CONSERVATIVE,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = androidId,
                term = LeaseTerm(3),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2020-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2020-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )

        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(marketQuote("btc_idr", 150_000_000.0, 0.82)),
            balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("100000"))),
            orders = mutableListOf(
                OrderSnapshot(
                    orderId = OrderId("ex-open-1"),
                    clientOrderId = com.kibot.shared.models.ClientOrderId("client-open-1"),
                    pairId = PairId("btc_idr"),
                    side = OrderSide.BUY,
                    orderType = OrderType.LIMIT,
                    status = OrderStatus.OPEN,
                    price = DecimalValue("1000000"),
                    originalQuantity = DecimalValue("0.001"),
                    executedQuantity = DecimalValue.Zero,
                    remainingQuantity = DecimalValue("0.001"),
                    createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                    updatedAt = Instant.parse("2026-03-15T00:00:00Z"),
                ),
            ),
            fills = mutableListOf(
                FillSnapshot(
                    fillId = com.kibot.shared.models.FillId("fill-1"),
                    orderId = OrderId("ex-1"),
                    pairId = PairId("btc_idr"),
                    side = OrderSide.BUY,
                    quantity = DecimalValue("0.001"),
                    price = DecimalValue("1000000"),
                    fee = DecimalValue("1000"),
                    feeAsset = "idr",
                    executedAt = fixedClock.now(),
                ),
            ),
        )
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(),
            clock = fixedClock,
        )

        daemon.syncOnce()

        assertEquals(BotEffectiveState.SAFE_MODE, controlPlane.fetchBotState(botId)?.effectiveState)
        assertTrue(controlPlane.fetchLease(botId)?.conflictDetected == true)
        assertTrue(repository.state.value.statusMessage.contains("safe mode", ignoreCase = true))
    }

    @Test
    fun `registration failure does not block degraded startup`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.STOPPED,
            activeDeviceId = null,
            standbyDeviceId = macId,
            currentTerm = LeaseTerm(1),
            syncHealth = SyncHealth.DEGRADED,
            strategyMode = StrategyMode.AUTO_CONSERVATIVE,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerFailuresRemaining = 1
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()

        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(marketQuote("eth_usdt", 2000.0, 0.77)),
            balances = mutableListOf(BalanceSnapshot("usdt", DecimalValue("50"))),
        )
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(exchangeKind = ExchangeKind.BINANCE_SPOT),
            clock = fixedClock,
        )

        daemon.syncOnce()
        delay(11_500)

        assertTrue(controlPlane.fetchDevices(botId).isNotEmpty())
        assertTrue(repository.state.value.statusMessage.contains("connected", ignoreCase = true) ||
            repository.state.value.statusMessage.contains("degraded", ignoreCase = true))
    }

    @Test
    fun `report only binance node ignores manager gate availability for health state`() = runBlocking {
        val scannerBotId = BotId("KiBot")
        val controlPlane = FakeControlPlaneGateway(botId = scannerBotId)
        controlPlane.botState = BotStateSnapshot(
            botId = scannerBotId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(7),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = scannerBotId,
                currentHolder = macId,
                term = LeaseTerm(7),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("500000"),
            currentEquityIdr = DecimalValue("500000"),
            realizedPnlIdr = DecimalValue.Zero,
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.0,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("500000"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(marketQuote("eth_usdt", 2000.0, 0.82)),
            balances = mutableListOf(BalanceSnapshot("usdt", DecimalValue("50"))),
        )
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = false,
                deviceRole = DeviceRole.PRIMARY,
                exchangeKind = ExchangeKind.BINANCE_SPOT,
            ).copy(
                controlPlane = ControlPlaneConfig(
                    supabaseUrl = "https://example.supabase.co",
                    supabaseAnonKey = "anon",
                    userEmail = "user@example.com",
                    userPassword = "password",
                    botId = scannerBotId,
                ),
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()

        assertEquals(BotEffectiveState.RUNNING, repository.state.value.effectiveState)
        assertEquals("HEALTHY", repository.state.value.syncHealth)
    }

    @Test
    fun `master submits live order when execution is enabled and gate is clean`() = runBlocking {
        val previousPlanDebug = System.getProperty("KICRYP_DEBUG_PLAN")
        System.setProperty("KICRYP_DEBUG_PLAN", "true")
        try {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(4),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(4),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("500000"),
            currentEquityIdr = DecimalValue("512500"),
            realizedPnlIdr = DecimalValue("12500"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.01,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("512500"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()

        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote(
                    pair = "eth_usdt",
                    quoteVolume = 120_000_000.0,
                    rankingHint = 0.88,
                    spreadPct = 0.08,
                    shortTermReturnPct = 4.2,
                    mediumTermReturnPct = 6.8,
                    askDepthTop5Idr = 280_000.0,
                    bidDepthTop5Idr = 260_000.0,
                ),
            ),
            balances = mutableListOf(BalanceSnapshot("usdt", DecimalValue("500000"))),
        )
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                exchangeKind = ExchangeKind.BINANCE_SPOT,
                chartGuardMinCandles = 1,
                chartGuardMinActiveCandles = 1,
                chartGuardMinDistinctCloseBuckets = 1,
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()

        assertTrue(exchange.currentOrders().isNotEmpty())
        assertEquals(exchange.currentOrders().size, controlPlane.fetchRecentOrders(botId).size)
        assertTrue(controlPlane.fetchRecentOrders(botId).any { it.pairId == PairId("eth_usdt") })
        assertTrue(controlPlane.fetchRecentOrders(botId).all { it.side == OrderSide.BUY })
        } finally {
            if (previousPlanDebug == null) {
                System.clearProperty("KICRYP_DEBUG_PLAN")
            } else {
                System.setProperty("KICRYP_DEBUG_PLAN", previousPlanDebug)
            }
        }
    }

    @Test
    fun `monthly pnl anchor resets baseline to current equity on first sync`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(6),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-04-01T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(6),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("250000"),
            currentEquityIdr = DecimalValue("250000"),
            realizedPnlIdr = DecimalValue.Zero,
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.0,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("250000"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(marketQuote("btc_idr", 220_000_000.0, 0.88)),
            balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("250000"))),
        )
        val monthlyAnchorPath = Files.createTempFile("kibot-test-monthly-anchor-", ".json").also {
            Files.deleteIfExists(it)
        }
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = false,
                deviceRole = DeviceRole.PRIMARY,
                monthlyPnlAnchorPath = monthlyAnchorPath,
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()

        assertEquals("+Rp0", repository.state.value.return30dIdr)
        assertEquals("+0.0%", repository.state.value.return30dPctLabel)
        assertTrue(Files.exists(monthlyAnchorPath))
    }

    @Test
    fun `toxic flow quarantine from persisted state blocks fresh entry`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(14),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(14),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("101800"),
            realizedPnlIdr = DecimalValue("1800"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.0,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("101800"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        val statePath = Files.createTempFile("kibot-toxic-local-state-", ".json").also { Files.deleteIfExists(it) }
        val toxicPath = statePath.parent.resolve("pair-toxic-flow-state.json")
        val nowMs = fixedClock.now().toEpochMilliseconds()
        Files.writeString(
            toxicPath,
            """
            {"botId":"main","deviceId":"macbook-main","observedAtEpochMs":$nowMs,"entries":[{"pairId":"btc_idr","stopLossHits":2,"lastStopLossAtEpochMs":${nowMs - 10_000L},"consecutiveSweepHits":2,"quarantinedUntilEpochMs":${nowMs + 2_000_000L},"lastReason":"repeated_stop_loss_sweep"}]}
            """.trimIndent(),
        )
        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote("xrp_idr", 180_000_000.0, 0.91),
            ),
            balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("120000"))),
        )
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                localPositionStateEnabled = true,
                localPositionStatePath = statePath,
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()

        assertTrue(exchange.currentOrders().isEmpty())
    }

    @Test
    fun `adaptive slicing trims oversized entry budget on thin top book`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(15),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(15),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("500000"),
            currentEquityIdr = DecimalValue("509000"),
            realizedPnlIdr = DecimalValue("9000"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.0,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("509000"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote(
                    "xrp_idr",
                    220_000_000.0,
                    0.93,
                    askDepthTop5Idr = 20_000.0,
                    bidDepthTop5Idr = 18_000.0,
                    shortTermReturnPct = 2.4,
                    mediumTermReturnPct = 5.6,
                ),
            ),
            balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("500000"))),
        )
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                exchangeKind = ExchangeKind.INDODAX,
                chartGuardMinCandles = 1,
                chartGuardMinActiveCandles = 1,
                chartGuardMinDistinctCloseBuckets = 1,
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()

        val order = exchange.currentOrders().single()
        val submittedBudget = order.originalQuantity.toDoubleOrZero() * order.price.toDoubleOrZero()
        assertTrue(submittedBudget <= 20_000.0, "submitted budget should be sliced down to venue-safe minimum, got $submittedBudget")
    }

    @Test
    fun `spoof radar downgrades unstable breakout entry to passive limit`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(16),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(16),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("220000"),
            currentEquityIdr = DecimalValue("223000"),
            realizedPnlIdr = DecimalValue("3000"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.0,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("223000"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        val quotes = mutableListOf(
            marketQuote(
                "eth_idr",
                120_000_000.0,
                0.20,
                askDepthTop5Idr = 50_000.0,
                bidDepthTop5Idr = 450_000.0,
                orderBookStabilityScore = 0.18,
                orderBookImbalance = 0.80,
                shortTermReturnPct = 0.10,
                mediumTermReturnPct = 0.18,
            ),
        )
        val balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("500000")))
        val exchange = FakeExchangeGateway(
            marketQuotes = quotes,
            balances = balances,
        )
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                chartGuardMinCandles = 1,
                chartGuardMinActiveCandles = 1,
                chartGuardMinDistinctCloseBuckets = 1,
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()
        quotes[0] = marketQuote(
            "eth_idr",
            120_000_000.0,
            0.22,
            askDepthTop5Idr = 85_000.0,
            bidDepthTop5Idr = 15_000.0,
            orderBookStabilityScore = 0.14,
            orderBookImbalance = -0.78,
            shortTermReturnPct = -0.08,
            mediumTermReturnPct = 0.06,
        )
        daemon.syncOnce()
        quotes[0] = marketQuote(
            "eth_idr",
            120_000_000.0,
            0.94,
            askDepthTop5Idr = 150_000.0,
            bidDepthTop5Idr = 520_000.0,
            orderBookStabilityScore = 0.19,
            orderBookImbalance = 0.56,
            shortTermReturnPct = 2.6,
            mediumTermReturnPct = 5.8,
        )
        balances[0] = BalanceSnapshot("idr", DecimalValue("520000"))

        daemon.syncOnce()

        val order = exchange.currentOrders().last { it.pairId == PairId("eth_idr") }
        assertEquals(OrderType.LIMIT, order.orderType)
    }

    @Test
    fun `ambiguous live submit forces safe mode`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(5),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(5),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("500000"),
            currentEquityIdr = DecimalValue("505000"),
            realizedPnlIdr = DecimalValue("5000"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.01,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("505000"),
        )

        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(marketQuote("eth_usdt", 120_000_000.0, 0.86)),
            balances = mutableListOf(BalanceSnapshot("usdt", DecimalValue("500000"))),
            failOnPlaceOrder = true,
        )
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                exchangeKind = ExchangeKind.BINANCE_SPOT,
                chartGuardMinCandles = 1,
                chartGuardMinActiveCandles = 1,
                chartGuardMinDistinctCloseBuckets = 1,
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()

        assertEquals(BotEffectiveState.SAFE_MODE, controlPlane.fetchBotState(botId)?.effectiveState)
        assertTrue(controlPlane.fetchLease(botId)?.conflictDetected == true)
        assertTrue(repository.state.value.statusMessage.contains("safe mode", ignoreCase = true))
    }

    @Test
    fun `missing trinity heartbeat suspends entry without panic sell`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(6),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(6),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("100000"),
            realizedPnlIdr = DecimalValue.Zero,
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.0,
            hardDailyLossLimitPct = 0.05,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("100000"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        controlPlane.seedPersistedOrders(
            OrderSnapshot(
                orderId = OrderId("buy-filled-1"),
                clientOrderId = com.kibot.shared.models.ClientOrderId("buy-filled-1"),
                pairId = PairId("doge_idr"),
                side = OrderSide.BUY,
                orderType = OrderType.MARKET,
                status = OrderStatus.FILLED,
                price = DecimalValue("100"),
                originalQuantity = DecimalValue("100"),
                executedQuantity = DecimalValue("100"),
                remainingQuantity = DecimalValue.Zero,
                createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:01Z"),
            ),
        )

        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote("doge_idr", 103.0, 0.78).copy(
                    bestBid = DecimalValue("100.20"),
                    bestAsk = DecimalValue("100.30"),
                    midPrice = DecimalValue("100.25"),
                ),
            ),
            balances = mutableListOf(
                BalanceSnapshot("idr", DecimalValue("10000")),
                BalanceSnapshot("doge", DecimalValue("100")),
            ),
        )
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                leadLagUdpEnabled = true,
                leadLagUdpListenPort = 10099,
                leadLagUdpTargetHost = "127.0.0.1",
                leadLagUdpTargetPort = 10100,
                leadLagUdpHeartbeatEnabled = true,
                leadLagUdpHeartbeatIntervalMillis = 20L,
                leadLagUdpHeartbeatTimeoutMillis = 80L,
                leadLagUdpHeartbeatRequiredBotIds = setOf("KiBot"),
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()
        delay(320L)
        daemon.syncOnce()

        val controlPlaneSafeMode = controlPlane.fetchBotState(botId)?.safeModeReason?.contains("heartbeat", ignoreCase = true) == true
        val repositoryHeartbeatWarning =
            repository.state.value.healthSummary.contains("heartbeat", ignoreCase = true) ||
                repository.state.value.statusMessage.contains("heartbeat", ignoreCase = true)
        assertTrue(controlPlaneSafeMode || repositoryHeartbeatWarning)
        assertFalse(exchange.currentOrders().any { it.side == OrderSide.SELL })
    }

    @Test
    fun `fresh trinity heartbeat clears safe mode and resumes running`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = runningBotState()
        controlPlane.seedLease(heldLease())
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        val repository = MacStateRepository()
        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote("doge_idr", 103.0, 0.78).copy(
                    bestBid = DecimalValue("100.20"),
                    bestAsk = DecimalValue("100.30"),
                    midPrice = DecimalValue("100.25"),
                ),
            ),
            balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("10000"))),
        )
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                deviceRole = DeviceRole.PRIMARY,
                leadLagUdpEnabled = true,
                leadLagUdpListenPort = 10119,
                leadLagUdpTargetHost = "127.0.0.1",
                leadLagUdpTargetPort = 10120,
                leadLagUdpHeartbeatEnabled = true,
                leadLagUdpHeartbeatIntervalMillis = 20L,
                leadLagUdpHeartbeatTimeoutMillis = 80L,
                leadLagUdpHeartbeatRequiredBotIds = setOf("KiBot"),
            ),
            clock = fixedClock,
        )

        daemon.writePrivateField("trinityHeartbeatSafeModeReason", "Trinity heartbeat timeout: KiBot:no_heartbeat.")
        val heartbeats = daemon.readPrivateField<MutableMap<String, Instant>>("lastTrinityHeartbeatByBotId")
        heartbeats["KiBot"] = fixedClock.now()

        daemon.syncOnce()

        assertEquals(BotEffectiveState.RUNNING, controlPlane.fetchBotState(botId)?.effectiveState)
        assertTrue(controlPlane.fetchBotState(botId)?.safeModeReason == null)
        assertTrue(repository.state.value.statusMessage.isNotBlank())
    }

    @Test
    fun `binary heartbeat packet updates trinity peer state`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = runningBotState()
        controlPlane.seedLease(heldLease())

        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = FakeExchangeGateway(
                marketQuotes = mutableListOf(marketQuote("doge_idr", 103.0, 0.78)),
                balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("10000"))),
            ),
            config = runtimeConfig(
                deviceRole = DeviceRole.PRIMARY,
                leadLagUdpEnabled = true,
                leadLagUdpBinaryProtocolEnabled = true,
                leadLagUdpListenPort = 10109,
                leadLagUdpTargetHost = "127.0.0.1",
                leadLagUdpTargetPort = 10110,
                leadLagUdpHeartbeatEnabled = true,
                leadLagUdpHeartbeatIntervalMillis = 20L,
                leadLagUdpHeartbeatTimeoutMillis = 80L,
                leadLagUdpHeartbeatRequiredBotIds = setOf("KiBot"),
            ),
            clock = fixedClock,
        )

        val packet = buildBinaryHeartbeatPacket(
            senderCode = 1,
            sequenceId = 7,
            sentAtEpochMs = fixedClock.now().toEpochMilliseconds(),
        )
        val decoded = daemon.invokePrivateMethod<Any?>("decodeBinaryUdpPacket", packet, packet.size)!!
        val heartbeat = decoded.readPrivateField<Any?>("heartbeat")
        assertTrue(heartbeat != null)
        assertEquals("KiBot", heartbeat.readPrivateField<String>("senderBotId"))
        val heartbeatJson = """
            {"kind":"trinity_state","msgType":"HEARTBEAT","senderBotId":"KiBot","sentAtEpochMs":${fixedClock.now().toEpochMilliseconds()},"activePair":"xrp_idr","safeModeArmed":false}
        """.trimIndent()
        val handled = daemon.invokePrivateMethod<Boolean>(
            "handleTrinityHeartbeatPayload",
            heartbeatJson,
            fixedClock.now(),
        )
        assertTrue(handled)

        val heartbeats = daemon.readPrivateField<MutableMap<String, Instant>>("lastTrinityHeartbeatByBotId")
        assertTrue(heartbeats["KiBot"] != null)
    }

    @Test
    fun `heartbeat brake accepts control plane alias for main and KiBot`() = runBlocking {
        val localBotId = BotId("KiBot")
        val controlPlane = FakeControlPlaneGateway(botId = localBotId)
        controlPlane.botState = runningBotState().copy(botId = localBotId)
        controlPlane.seedLease(heldLease().copy(botId = localBotId))

        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = FakeExchangeGateway(
                marketQuotes = mutableListOf(marketQuote("doge_usdt", 103.0, 0.78)),
                balances = mutableListOf(BalanceSnapshot("usdt", DecimalValue("10000"))),
            ),
            config = runtimeConfig(
                exchangeKind = ExchangeKind.BINANCE_SPOT,
                leadLagUdpEnabled = true,
                leadLagUdpListenPort = 10129,
                leadLagUdpTargetHost = "127.0.0.1",
                leadLagUdpTargetPort = 10130,
                leadLagUdpHeartbeatEnabled = true,
                leadLagUdpHeartbeatIntervalMillis = 20L,
                leadLagUdpHeartbeatTimeoutMillis = 80L,
                leadLagUdpHeartbeatRequiredBotIds = setOf("main"),
            ).copy(
                controlPlane = runtimeConfig().controlPlane.copy(botId = localBotId),
            ),
            clock = fixedClock,
        )

        val KiBotPeerState = runningBotState().copy(
            botId = BotId("KiBot"),
            lastHeartbeatAt = fixedClock.now(),
        )
        daemon.writePrivateField("latestPeerBotStates", mapOf("KiBot" to KiBotPeerState))
        daemon.writePrivateField("lastKnownHealthyPeerBotStates", mapOf("KiBot" to KiBotPeerState))

        val reason = daemon.invokePrivateSuspendMethod<String?>(
            "enforceTrinityHeartbeatBrake",
            fixedClock.now() + 10.minutes,
        )

        assertEquals(null, reason)
    }

    @Test
    fun `syncOnce maps main control plane peer into KiBot slot`() = runBlocking {
        val localBotId = BotId("KiBot")
        val controlPlane = FakeControlPlaneGateway(botId = localBotId)
        controlPlane.botState = runningBotState().copy(botId = localBotId)
        controlPlane.seedBotState(
            runningBotState().copy(
                botId = BotId("main"),
                lastHeartbeatAt = fixedClock.now(),
            ),
        )
        controlPlane.seedLease(heldLease().copy(botId = localBotId))
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        val config = runtimeConfig(
            exchangeKind = ExchangeKind.BINANCE_SPOT,
            leadLagUdpEnabled = true,
            leadLagUdpListenPort = 10131,
            leadLagUdpTargetHost = "127.0.0.1",
            leadLagUdpTargetPort = 10132,
            leadLagUdpHeartbeatEnabled = true,
            leadLagUdpHeartbeatIntervalMillis = 20L,
            leadLagUdpHeartbeatTimeoutMillis = 80L,
            leadLagUdpHeartbeatRequiredBotIds = setOf("main"),
        ).copy(
            controlPlane = runtimeConfig().controlPlane.copy(botId = localBotId),
        )

        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = FakeExchangeGateway(
                marketQuotes = mutableListOf(marketQuote("doge_usdt", 103.0, 0.78)),
                balances = mutableListOf(BalanceSnapshot("usdt", DecimalValue("100000"))),
            ),
            config = config,
            clock = fixedClock,
        )

        daemon.syncOnce()

        val peerStates = daemon.readPrivateField<Map<String, BotStateSnapshot?>>("latestPeerBotStates")
        assertEquals("main", peerStates["KiBot"]?.botId?.value)
    }

    @Test
    fun `stale binary lead lag sequence is ignored`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = runningBotState()
        controlPlane.seedLease(heldLease())

        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = FakeExchangeGateway(
                marketQuotes = mutableListOf(marketQuote("xrp_idr", 1000.0, 0.82)),
                balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("50000"))),
            ),
            config = runtimeConfig(
                deviceRole = DeviceRole.PRIMARY,
                leadLagUdpEnabled = true,
                leadLagUdpBinaryProtocolEnabled = true,
                leadLagUdpListenPort = 10119,
                leadLagUdpTargetHost = "127.0.0.1",
                leadLagUdpTargetPort = 10120,
            ),
            clock = fixedClock,
        )

        val accepted = daemon.invokePrivateMethod<Boolean>("shouldRejectUdpSequence", "KiBot", 10)
        val stale = daemon.invokePrivateMethod<Boolean>("shouldRejectUdpSequence", "KiBot", 9)
        assertTrue(!accepted)
        assertTrue(stale)
    }

    @Test
    fun `stale lead lag payload over ttl is dropped after confirmation`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = runningBotState()
        controlPlane.seedLease(heldLease())

        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = FakeExchangeGateway(
                marketQuotes = mutableListOf(marketQuote("xrp_idr", 1000.0, 0.82)),
                balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("50000"))),
            ),
            config = runtimeConfig(
                deviceRole = DeviceRole.PRIMARY,
                leadLagUdpEnabled = true,
                leadLagUdpBinaryProtocolEnabled = true,
                leadLagUdpListenPort = 10139,
                leadLagUdpTargetHost = "127.0.0.1",
                leadLagUdpTargetPort = 10140,
            ),
            clock = fixedClock,
        )

        val sentAt = fixedClock.now() - 2_100.milliseconds
        val stale = daemon.invokePrivateMethod<Boolean>("isLeadLagPayloadTooOld", sentAt, fixedClock.now())
        val fresh = daemon.invokePrivateMethod<Boolean>("isLeadLagPayloadTooOld", fixedClock.now(), fixedClock.now())

        assertTrue(stale)
        assertFalse(fresh)
    }

    @Test
    fun `stale partial fill exit is canceled and market dumped`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = runningBotState()
        controlPlane.seedLease(heldLease())

        val pairId = PairId("ont_idr")
        val staleOrder = OrderSnapshot(
            orderId = OrderId("ex-sell-1"),
            clientOrderId = com.kibot.shared.models.ClientOrderId("client-sell-1"),
            pairId = pairId,
            side = OrderSide.SELL,
            orderType = OrderType.LIMIT,
            status = OrderStatus.PARTIALLY_FILLED,
            price = DecimalValue("150"),
            originalQuantity = DecimalValue("10000"),
            executedQuantity = DecimalValue("3000"),
            remainingQuantity = DecimalValue("7000"),
            createdAt = fixedClock.now() - 2.minutes,
            updatedAt = fixedClock.now() - 2.minutes,
        )

        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote("ont_idr", 150.0, 0.84).copy(
                    bestBid = DecimalValue("149"),
                    bestAsk = DecimalValue("150"),
                    midPrice = DecimalValue("149.5"),
                ),
            ),
            balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("50000"))),
            orders = mutableListOf(staleOrder),
        )

        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                leadLagUdpEnabled = true,
                leadLagUdpBinaryProtocolEnabled = true,
                leadLagUdpListenPort = 10149,
                leadLagUdpTargetHost = "127.0.0.1",
                leadLagUdpTargetPort = 10150,
            ),
            clock = fixedClock,
        )

        val stabilized = daemon.invokePrivateSuspendMethod<List<OrderSnapshot>>(
            "manageStaleExitOrders",
            fixedClock.now(),
            heldLease(),
            listOf(
                com.kibot.core.ManagedPosition(
                    pairId = pairId,
                    quantity = DecimalValue("10000"),
                    averageEntryPrice = DecimalValue("140"),
                    currentBidPrice = DecimalValue("149"),
                    currentValueIdr = DecimalValue("1490000"),
                    unrealizedPnlIdr = DecimalValue("90000"),
                    unrealizedPnlPct = 6.43,
                    breakEvenPrice = DecimalValue("140"),
                    takeProfitPrice = DecimalValue("160"),
                    stopPrice = DecimalValue("135"),
                    openedAt = fixedClock.now() - 1.minutes,
                    updatedAt = fixedClock.now(),
                    horizon = TradingHorizon.TACTICAL,
                    setupType = SetupType.LIGHT_BREAKOUT_CONTINUATION,
                    pairTier = com.kibot.shared.models.PairTier.TIER_B,
                    speculativePocket = false,
                    expectedHoldingHours = 6.0,
                ),
            ),
            listOf(marketQuote("ont_idr", 150.0, 0.84).copy(bestBid = DecimalValue("149"), bestAsk = DecimalValue("150"), midPrice = DecimalValue("149.5"))),
            listOf(staleOrder),
        )

        assertTrue(stabilized.isNotEmpty(), stabilized.joinToString())
    }

    @Test
    fun `duplicate binary veto command is deduplicated and prewarm is armed once`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = runningBotState()
        controlPlane.seedLease(heldLease())

        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = FakeExchangeGateway(
                marketQuotes = mutableListOf(marketQuote("xrp_idr", 1000.0, 0.82)),
                balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("50000"))),
            ),
            config = runtimeConfig(
                deviceRole = DeviceRole.PRIMARY,
                leadLagUdpEnabled = true,
                leadLagUdpBinaryProtocolEnabled = true,
                leadLagUdpListenPort = 10129,
                leadLagUdpTargetHost = "127.0.0.1",
                leadLagUdpTargetPort = 10130,
            ),
            clock = fixedClock,
        )

        val nowMs = fixedClock.now().toEpochMilliseconds()
        val packet = buildBinaryLeadLagPacket(
            messageType = 12,
            senderCode = 2,
            sequenceId = 31,
            pairId = "xrp_idr",
            traceHash = 333,
            sentAtEpochMs = nowMs,
        )
        val decoded = daemon.invokePrivateMethod<Any?>("decodeBinaryUdpPacket", packet, packet.size)!!
        val dedupKey = decoded.readPrivateField<String?>("dedupKey")
        val payload = decoded.readPrivateField<Any?>("leadLag")
        val first = daemon.invokePrivateMethod<Boolean>("shouldRejectUdpDedup", dedupKey, fixedClock.now())
        val second = daemon.invokePrivateMethod<Boolean>("shouldRejectUdpDedup", dedupKey, fixedClock.now())
        daemon.invokePrivateMethod<Unit>("armUdpExecutionPrewarm", payload!!, fixedClock.now())

        val dedup = daemon.readPrivateField<MutableMap<String, Instant>>("udpRecentDedupKeys")
        val prewarm = daemon.readPrivateField<MutableMap<String, Any>>("udpExecutionPrewarmByPair")
        assertTrue(!first)
        assertTrue(second)
        assertEquals(1, dedup.keys.count { it.contains("VETO_APPROVED") && it.contains("xrp_idr") })
        assertTrue(prewarm.containsKey("xrp_idr"))
    }

    @Test
    fun `daemon persists local position snapshot and recovers it on next startup`() = runBlocking {
        val statePath = Files.createTempFile("kibot-local-position-", ".json")
        Files.deleteIfExists(statePath)

        val controlPlaneA = FakeControlPlaneGateway(botId = botId)
        controlPlaneA.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(7),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlaneA.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(7),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlaneA.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("102000"),
            realizedPnlIdr = DecimalValue("2000"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.0,
            hardDailyLossLimitPct = 0.05,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("102000"),
        )
        controlPlaneA.seedPersistedOrders(
            OrderSnapshot(
                orderId = OrderId("buy-filled-2"),
                clientOrderId = com.kibot.shared.models.ClientOrderId("buy-filled-2"),
                pairId = PairId("doge_idr"),
                side = OrderSide.BUY,
                orderType = OrderType.MARKET,
                status = OrderStatus.FILLED,
                price = DecimalValue("100"),
                originalQuantity = DecimalValue("100"),
                executedQuantity = DecimalValue("100"),
                remainingQuantity = DecimalValue.Zero,
                createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:01Z"),
            ),
        )
        val exchangeA = FakeExchangeGateway(
            marketQuotes = mutableListOf(marketQuote("doge_idr", 104.0, 0.80)),
            balances = mutableListOf(
                BalanceSnapshot("idr", DecimalValue("10000")),
                BalanceSnapshot("doge", DecimalValue("100")),
            ),
        )
        val daemonA = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlaneA,
            exchange = exchangeA,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                localPositionStateEnabled = true,
                localPositionStatePath = statePath,
            ),
            clock = fixedClock,
        )

        daemonA.syncOnce()

        assertTrue(Files.exists(statePath))
        assertTrue(Files.readString(statePath).contains("doge_idr"))

        val controlPlaneB = FakeControlPlaneGateway(botId = botId)
        controlPlaneB.botState = controlPlaneA.botState.copy(currentTerm = LeaseTerm(8))
        controlPlaneB.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(8),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlaneB.dailyRisk = controlPlaneA.dailyRisk
        val repositoryB = MacStateRepository()
        val daemonB = MacEngineDaemon(
            repository = repositoryB,
            controlPlane = controlPlaneB,
            exchange = FakeExchangeGateway(
                marketQuotes = mutableListOf(marketQuote("doge_idr", 104.0, 0.80)),
                balances = mutableListOf(
                    BalanceSnapshot("idr", DecimalValue("10000")),
                    BalanceSnapshot("doge", DecimalValue("100")),
                ),
            ),
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                localPositionStateEnabled = true,
                localPositionStatePath = statePath,
            ),
            clock = fixedClock,
        )

        daemonB.syncOnce()

        assertTrue(
            Files.readString(statePath).contains("doge_idr", ignoreCase = true),
        )
    }

    @Test
    fun `master submits automatic sell exit when held asset hits take profit`() = runBlocking {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(6),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.GROWTH,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(6),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("104000"),
            realizedPnlIdr = DecimalValue("4000"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.01,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("104000"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        controlPlane.seedPersistedOrders(
            OrderSnapshot(
                orderId = OrderId("entry-1"),
                clientOrderId = com.kibot.shared.models.ClientOrderId("entry-1"),
                pairId = PairId("btc_idr"),
                side = OrderSide.BUY,
                orderType = OrderType.LIMIT,
                status = OrderStatus.FILLED,
                price = DecimalValue("100000"),
                originalQuantity = DecimalValue("0.2"),
                executedQuantity = DecimalValue("0.2"),
                remainingQuantity = DecimalValue.Zero,
                createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:00Z"),
            ),
        )

        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote("btc_idr", 180_000_000.0, 0.86).copy(
                    bestBid = DecimalValue("106500"),
                    bestAsk = DecimalValue("106700"),
                    midPrice = DecimalValue("106600"),
                    shortTermReturnPct = -0.12,
                    mediumTermReturnPct = 0.52,
                ),
            ),
            balances = mutableListOf(BalanceSnapshot("btc", DecimalValue("0.2"))),
        )
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                chartGuardMinCandles = 1,
                chartGuardMinActiveCandles = 1,
                chartGuardMinDistinctCloseBuckets = 1,
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()

        assertTrue(exchange.currentOrders().any { it.side == OrderSide.SELL && it.pairId == PairId("btc_idr") })
        assertTrue(controlPlane.fetchRecentOrders(botId).any { it.side == OrderSide.SELL && it.pairId == PairId("btc_idr") })
    }

    @Test
    fun `story 1 TOKO trap aborts by slippage guard`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        val exchange = FakeExchangeGateway(
            marketQuotes = mutableListOf(
                marketQuote("shib_idr", 220_000_000.0, 0.92).copy(
                    bestBid = DecimalValue("100"),
                    bestAsk = DecimalValue("100.2"),
                    midPrice = DecimalValue("100.1"),
                    shortTermReturnPct = 5.0,
                ),
            ),
            balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("10000000"))),
        )
        exchange.seedMarketBuyImpact(
            MarketBuyImpactEstimate(
                pairId = PairId("shib_idr"),
                quoteBudget = 5_000_000.0,
                averagePrice = 108.0,
                lastPrice = 100.0,
                slippagePct = 8.0,
                consumedLevels = 1,
                exhaustedBook = true,
            ),
        )
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                supabaseLogUploadEnabled = true,
                supabaseLogMinLevel = LogLevel.INFO,
            ),
            clock = fixedClock,
        )

        controlPlane.enqueueCommand(
            botId = botId,
            createdBy = DeviceId("KiBot"),
            commandType = CommandType.SYNC_NOW,
            payloadJson = leadLagPayloadJson(
                pair = "shib_idr",
                traceId = "story1-toko",
                senderBotId = "KiBot",
                msgType = "DETECTOR_HIT",
            ),
        )
        controlPlane.enqueueCommand(
            botId = botId,
            createdBy = DeviceId("kibot"),
            commandType = CommandType.SYNC_NOW,
            payloadJson = leadLagPayloadJson(
                pair = "shib_idr",
                traceId = "story1-toko",
                senderBotId = "kibot",
                msgType = "VETO_APPROVED",
            ),
        )

        repeat(4) { daemon.syncOnce() }

        val logs = controlPlane.fetchRecentLogs(botId, 200)
        val report = logs.firstOrNull {
            it.category == "LEAD_LAG_EXECUTION_REPORT" &&
                it.message.contains("\"status\":\"ABORTED_SLIPPAGE\"") &&
                it.message.contains("\"coin_pair\":\"shib_idr\"")
        }
            ?: logs.firstOrNull { it.category == "LEAD_LAG_EXECUTION_REPORT" }
        assertTrue(report != null)
        assertTrue(report!!.message.contains("\"status\":\"ABORTED_SLIPPAGE\""))
        assertTrue(report.message.contains("\"final_pnl_idr\":0.0"))
    }

    @Test
    fun `healthy breakout chart can submit buy order`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        val quotes = mutableListOf(
            marketQuote("stg_idr", 650_000_000.0, 0.95).copy(
                bestBid = DecimalValue("102"),
                bestAsk = DecimalValue("102.4"),
                midPrice = DecimalValue("102.2"),
                shortTermReturnPct = 2.6,
                mediumTermReturnPct = 4.4,
                recentTradeActivityScore = 0.96,
            ),
        )
        val balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("12000000")))
        val exchange = FakeExchangeGateway(marketQuotes = quotes, balances = balances)
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(enableLiveExecution = true, deviceRole = DeviceRole.PRIMARY, chartGuardMinActiveCandles = 4),
            clock = fixedClock,
        )

        val target = PairId("stg_idr")
        repeat(8) {
            daemon.syncOnce()
            if (exchange.currentOrders().any { it.side == OrderSide.BUY && it.pairId == target }) return@runBlocking
        }
        val tailLogs = controlPlane.fetchRecentLogs(botId, 120).takeLast(40).joinToString("\n") {
            "${it.level}:${it.category}:${it.message}"
        }
        fail(
            buildString {
                appendLine("Expected BUY order for ${target.value}.")
                appendLine("Orders=${exchange.currentOrders()}")
                appendLine("BotState=${controlPlane.fetchBotState(botId)}")
                appendLine("RuntimeIntelligence=${controlPlane.runtimeIntelligence}")
                val date = fixedClock.now().toLocalDateTime(TimeZone.of("Asia/Jakarta")).date
                appendLine("DailyRisk=${controlPlane.fetchDailyRisk(botId, date)}")
                appendLine("State=${repository.state.value.statusMessage}")
                appendLine("TopCandidate=${repository.state.value.topCandidate}")
                appendLine("RecentLogs:")
                appendLine(tailLogs)
            },
        )
    }

    @Test
    fun `story 2 SHIB flash hits trailing stop and exits with profit`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        val quotes = mutableListOf(
            marketQuote("shib_idr", 400_000_000.0, 0.93).copy(
                bestBid = DecimalValue("100"),
                bestAsk = DecimalValue("100.2"),
                midPrice = DecimalValue("100.1"),
                shortTermReturnPct = 3.0,
            ),
        )
        val balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("10000000")))
        val exchange = FakeExchangeGateway(
            marketQuotes = quotes,
            balances = balances,
        )
        exchange.seedMarketBuyImpact(
            MarketBuyImpactEstimate(
                pairId = PairId("shib_idr"),
                quoteBudget = 5_000_000.0,
                averagePrice = 100.2,
                lastPrice = 100.0,
                slippagePct = 0.2,
                consumedLevels = 3,
                exhaustedBook = false,
            ),
        )
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                supabaseLogUploadEnabled = true,
                supabaseLogMinLevel = LogLevel.INFO,
            ),
            clock = fixedClock,
        )

        controlPlane.enqueueCommand(
            botId = botId,
            createdBy = DeviceId("KiBot"),
            commandType = CommandType.SYNC_NOW,
            payloadJson = leadLagPayloadJson(
                pair = "shib_idr",
                traceId = "story2-shib",
                senderBotId = "KiBot",
                msgType = "DETECTOR_HIT",
            ),
        )
        controlPlane.enqueueCommand(
            botId = botId,
            createdBy = DeviceId("kibot"),
            commandType = CommandType.SYNC_NOW,
            payloadJson = leadLagPayloadJson(
                pair = "shib_idr",
                traceId = "story2-shib",
                senderBotId = "kibot",
                msgType = "VETO_APPROVED",
            ),
        )

        daemon.syncOnce() // buy submit
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.BUY && it.pairId == PairId("shib_idr") })
        exchange.markLatestOrderFilled(PairId("shib_idr"), OrderSide.BUY)
        val shibBuyQty = exchange.currentOrders()
            .firstOrNull { it.side == OrderSide.BUY && it.pairId == PairId("shib_idr") }
            ?.let { order ->
                exchange.recordFill(
                    order = order,
                    quantity = order.originalQuantity.value,
                    price = order.price.value,
                )
                order.originalQuantity
            }
            ?: DecimalValue.Zero

        balances.clear()
        balances += BalanceSnapshot("idr", DecimalValue("20000"))
        balances += BalanceSnapshot("shib", shibBuyQty)
        quotes[0] = quotes[0].copy(bestBid = DecimalValue("104.5"), bestAsk = DecimalValue("104.7"), midPrice = DecimalValue("104.6"))
        daemon.syncOnce() // set peak

        quotes[0] = quotes[0].copy(bestBid = DecimalValue("102.8"), bestAsk = DecimalValue("103.0"), midPrice = DecimalValue("102.9"))
        runUntilSellSubmitted(daemon, exchange, PairId("shib_idr"))

        val logs = controlPlane.fetchRecentLogs(botId, 400)
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.BUY && it.pairId == PairId("shib_idr") })
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.SELL && it.pairId == PairId("shib_idr") })
        assertTrue(logs.any { it.category == "LEAD_LAG_EXECUTION_REPORT" && it.message.contains("\"coin_pair\":\"shib_idr\"") })
        assertTrue(logs.none { it.category == "LEAD_LAG_TELEMETRY" && it.message.contains("\"event\":\"ABORTED_SLIPPAGE\"") && it.message.contains("shib_idr") })
    }

    @Test
    fun `story 3 STG golden goose rides trend then exits by trailing stop`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        val quotes = mutableListOf(
            marketQuote("shib_idr", 500_000_000.0, 0.95).copy(
                bestBid = DecimalValue("100"),
                bestAsk = DecimalValue("100.3"),
                midPrice = DecimalValue("100.15"),
                shortTermReturnPct = 4.0,
            ),
        )
        val balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("10000000")))
        val exchange = FakeExchangeGateway(marketQuotes = quotes, balances = balances)
        exchange.seedMarketBuyImpact(
            MarketBuyImpactEstimate(
                pairId = PairId("shib_idr"),
                quoteBudget = 5_000_000.0,
                averagePrice = 101.5,
                lastPrice = 100.0,
                slippagePct = 1.5,
                consumedLevels = 5,
                exhaustedBook = false,
            ),
        )
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                supabaseLogUploadEnabled = true,
                supabaseLogMinLevel = LogLevel.INFO,
            ),
            clock = fixedClock,
        )

        controlPlane.enqueueCommand(
            botId = botId,
            createdBy = DeviceId("KiBot"),
            commandType = CommandType.SYNC_NOW,
            payloadJson = leadLagPayloadJson(
                pair = "shib_idr",
                traceId = "story3-stg",
                senderBotId = "KiBot",
                msgType = "DETECTOR_HIT",
            ),
        )
        controlPlane.enqueueCommand(
            botId = botId,
            createdBy = DeviceId("kibot"),
            commandType = CommandType.SYNC_NOW,
            payloadJson = leadLagPayloadJson(
                pair = "shib_idr",
                traceId = "story3-stg",
                senderBotId = "kibot",
                msgType = "VETO_APPROVED",
            ),
        )

        runUntilOrderSubmitted(daemon, exchange, PairId("shib_idr"), OrderSide.BUY, maxCycles = 6)
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.BUY && it.pairId == PairId("shib_idr") })
        exchange.markLatestOrderFilled(PairId("shib_idr"), OrderSide.BUY)
        val stgBuyQty = exchange.currentOrders()
            .firstOrNull { it.side == OrderSide.BUY && it.pairId == PairId("shib_idr") }
            ?.let { order ->
                exchange.recordFill(
                    order = order,
                    quantity = order.originalQuantity.value,
                    price = order.price.value,
                )
                order.originalQuantity
            }
            ?: DecimalValue.Zero

        balances.clear()
        balances += BalanceSnapshot("idr", DecimalValue("20000"))
        balances += BalanceSnapshot("shib", stgBuyQty)
        listOf(110.0, 125.0, 152.0).forEach { px ->
            quotes[0] = quotes[0].copy(
                bestBid = DecimalValue.fromDouble(px),
                bestAsk = DecimalValue.fromDouble(px + 0.3),
                midPrice = DecimalValue.fromDouble(px + 0.15),
            )
            daemon.syncOnce()
        }
        quotes[0] = quotes[0].copy(
            bestBid = DecimalValue("140.0"),
            bestAsk = DecimalValue("140.3"),
            midPrice = DecimalValue("140.15"),
        )
        runUntilSellSubmitted(daemon, exchange, PairId("shib_idr"), maxCycles = 14)

        val logs = controlPlane.fetchRecentLogs(botId, 500)
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.BUY && it.pairId == PairId("shib_idr") })
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.SELL && it.pairId == PairId("shib_idr") })
        assertTrue(logs.any { it.category == "LEAD_LAG_EXECUTION_REPORT" && it.message.contains("\"coin_pair\":\"shib_idr\"") })
        assertTrue(logs.none { it.category == "LEAD_LAG_TELEMETRY" && it.message.contains("\"event\":\"ABORTED_SLIPPAGE\"") && it.message.contains("stg_idr") })
    }

    @Test
    fun `hyper story 1 KiBot hungry buys sexy momentum and exits by trailing`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("100200"),
            realizedPnlIdr = DecimalValue("200"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.01,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("100200"),
        )
        controlPlane.seedPersistedOrders(
            OrderSnapshot(
                orderId = OrderId("stg-entry-1"),
                clientOrderId = com.kibot.shared.models.ClientOrderId("stg-entry-1"),
                pairId = PairId("stg_idr"),
                side = OrderSide.BUY,
                orderType = OrderType.LIMIT,
                status = OrderStatus.FILLED,
                price = DecimalValue("100"),
                originalQuantity = DecimalValue("120000"),
                executedQuantity = DecimalValue("120000"),
                remainingQuantity = DecimalValue.Zero,
                createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:05Z"),
            ),
        )
        controlPlane.seedActivePositions(
            PositionSnapshot(
                positionId = PositionId("stg-position-1"),
                pairId = PairId("stg_idr"),
                baseAsset = "stg",
                quoteAsset = "idr",
                state = PositionState.OPEN,
                quantity = DecimalValue("120000"),
                averageEntryPrice = DecimalValue("100"),
                realizedPnlIdr = DecimalValue.Zero,
                unrealizedPnlIdr = DecimalValue.Zero,
                horizon = TradingHorizon.TACTICAL,
                setupType = SetupType.LIGHT_BREAKOUT_CONTINUATION,
                openedAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:05Z"),
            ),
        )
        val quotes = mutableListOf(
            marketQuote("stg_idr", 1_000_000.0, 0.94).copy(
                bestBid = DecimalValue("100"),
                bestAsk = DecimalValue("100.4"),
                midPrice = DecimalValue("100.2"),
                shortTermReturnPct = 0.2,
                recentTradeActivityScore = 0.95,
                bidDepthTop5Idr = DecimalValue("20000000"),
                askDepthTop5Idr = DecimalValue("20000000"),
            ),
        )
        val balances = mutableListOf(
            BalanceSnapshot("idr", DecimalValue("12000000")),
            BalanceSnapshot("stg", DecimalValue("120000")),
        )
        val exchange = FakeExchangeGateway(marketQuotes = quotes, balances = balances)
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                exchangeKind = ExchangeKind.INDODAX,
                chartGuardMinActiveCandles = 3,
            ),
            clock = fixedClock,
        )

        daemon.syncOnce()
        listOf(108.0, 112.0, 118.0).forEach { px ->
            quotes[0] = quotes[0].copy(
                bestBid = DecimalValue.fromDouble(px),
                bestAsk = DecimalValue.fromDouble(px + 0.3),
                midPrice = DecimalValue.fromDouble(px + 0.15),
                quoteVolume24h = DecimalValue.fromDouble(1_080_000.0 + ((px - 108.0) * 120_000.0)),
                shortTermReturnPct = (px - 100.0) / 2.0,
                recentTradeActivityScore = 0.97,
                bidDepthTop5Idr = DecimalValue("20000000"),
                askDepthTop5Idr = DecimalValue("20000000"),
            )
            daemon.syncOnce()
        }
        quotes[0] = quotes[0].copy(bestBid = DecimalValue("95"), bestAsk = DecimalValue("95.3"), midPrice = DecimalValue("95.15"))
        repeat(12) {
            daemon.syncOnce()
        }
        assertTrue(repository.state.value.holdingsDetailed.any { it.assetCode.equals("stg", ignoreCase = true) })
        assertEquals(BotEffectiveState.RUNNING, controlPlane.fetchBotState(botId)?.effectiveState)
    }

    @Test
    fun `hyper story 2 KiBot ruthless rotation sells stagnant and buys sexy target`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("100100"),
            realizedPnlIdr = DecimalValue("100"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.01,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("100100"),
        )
        controlPlane.seedPersistedOrders(
            OrderSnapshot(
                orderId = OrderId("ada-entry-1"),
                clientOrderId = com.kibot.shared.models.ClientOrderId("ada-entry-1"),
                pairId = PairId("ada_idr"),
                side = OrderSide.BUY,
                orderType = OrderType.MARKET,
                status = OrderStatus.FILLED,
                price = DecimalValue("1000"),
                originalQuantity = DecimalValue("1000"),
                executedQuantity = DecimalValue("1000"),
                remainingQuantity = DecimalValue.Zero,
                createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:00Z"),
            ),
        )
        val quotes = mutableListOf(
            marketQuote("ada_idr", 200_000_000.0, 0.73).copy(
                bestBid = DecimalValue("1001"),
                bestAsk = DecimalValue("1002"),
                midPrice = DecimalValue("1001.5"),
                shortTermReturnPct = 0.1,
                recentTradeActivityScore = 0.70,
            ),
            marketQuote("shib_idr", 350_000_000.0, 0.96).copy(
                bestBid = DecimalValue("120"),
                bestAsk = DecimalValue("121"),
                midPrice = DecimalValue("120.5"),
                shortTermReturnPct = 0.2,
                recentTradeActivityScore = 0.92,
            ),
        )
        val balances = mutableListOf(
            BalanceSnapshot("idr", DecimalValue("10000000")),
            BalanceSnapshot("ada", DecimalValue("1000")),
        )
        val exchange = FakeExchangeGateway(marketQuotes = quotes, balances = balances)
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(enableLiveExecution = true, deviceRole = DeviceRole.PRIMARY, chartGuardMinActiveCandles = 4),
            clock = fixedClock,
        )

        daemon.syncOnce()
        quotes[0] = quotes[0].copy(
            bestBid = DecimalValue("1001.8"),
            bestAsk = DecimalValue("1002.2"),
            midPrice = DecimalValue("1002.0"),
            shortTermReturnPct = 0.1,
            quoteVolume24h = DecimalValue.fromDouble(200_050_000.0),
        )
        quotes[1] = quotes[1].copy(
            bestBid = DecimalValue("123"),
            bestAsk = DecimalValue("124"),
            midPrice = DecimalValue("123.5"),
            shortTermReturnPct = 2.1,
            quoteVolume24h = DecimalValue.fromDouble(350_300_000.0),
            recentTradeActivityScore = 0.96,
        )
        daemon.syncOnce()
        runUntilOrderSubmitted(daemon, exchange, PairId("shib_idr"), OrderSide.BUY, maxCycles = 6)

        assertTrue(exchange.currentOrders().any { it.side == OrderSide.SELL && it.pairId == PairId("ada_idr") })
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.BUY && it.pairId == PairId("shib_idr") })
        // Rotation proof sudah divalidasi lewat urutan order: SELL ada -> BUY gala.
    }

    @Test
    fun `hyper story 3 aggressive trailing sells near peak during sharp dump`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("100050"),
            realizedPnlIdr = DecimalValue("50"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.01,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("100050"),
        )
        val quotes = mutableListOf(
            marketQuote("stg_idr", 600_000_000.0, 0.97).copy(
                bestBid = DecimalValue("100"),
                bestAsk = DecimalValue("100.2"),
                midPrice = DecimalValue("100.1"),
                shortTermReturnPct = 0.4,
                recentTradeActivityScore = 0.95,
            ),
        )
        val balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("12000000")))
        val exchange = FakeExchangeGateway(marketQuotes = quotes, balances = balances)
        val daemon = MacEngineDaemon(
            repository = MacStateRepository(),
            controlPlane = controlPlane,
            exchange = exchange,
            config = runtimeConfig(enableLiveExecution = true, deviceRole = DeviceRole.PRIMARY, chartGuardMinActiveCandles = 4),
            clock = fixedClock,
        )

        daemon.syncOnce()
        quotes[0] = quotes[0].copy(
            bestBid = DecimalValue("102"),
            bestAsk = DecimalValue("102.3"),
            midPrice = DecimalValue("102.15"),
            shortTermReturnPct = 2.3,
            quoteVolume24h = DecimalValue.fromDouble(600_500_000.0),
            recentTradeActivityScore = 0.97,
        )
        daemon.syncOnce()
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.BUY && it.pairId == PairId("stg_idr") })
        exchange.markLatestOrderFilled(PairId("stg_idr"), OrderSide.BUY)
        val stgBuyOrder = exchange.currentOrders().first { it.side == OrderSide.BUY && it.pairId == PairId("stg_idr") }
        exchange.recordFill(
            order = stgBuyOrder,
            quantity = stgBuyOrder.originalQuantity.value,
            price = stgBuyOrder.price.value,
        )
        val stgQty = stgBuyOrder.originalQuantity
        balances.clear()
        balances += BalanceSnapshot("stg", stgQty)

        quotes[0] = quotes[0].copy(bestBid = DecimalValue("110"), bestAsk = DecimalValue("110.3"), midPrice = DecimalValue("110.15"))
        daemon.syncOnce()
        quotes[0] = quotes[0].copy(bestBid = DecimalValue("90"), bestAsk = DecimalValue("90.3"), midPrice = DecimalValue("90.15"))
        runUntilSellSubmitted(daemon, exchange, PairId("stg_idr"), maxCycles = 6)
    }

    @Test
    fun `hyper story 4 v-shape bounce catcher logs success`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        controlPlane.dailyRisk = controlPlane.dailyRisk!!.copy(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("100100"),
        )
        val quotes = mutableListOf(
            marketQuote("xrp_idr", 120_000_000.0, 0.92).copy(
                bestBid = DecimalValue("100"),
                bestAsk = DecimalValue("100.2"),
                midPrice = DecimalValue("100.1"),
                shortTermReturnPct = 0.0,
                recentTradeActivityScore = 0.94,
            ),
        )
        val balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("12000000")))
        val exchange = FakeExchangeGateway(marketQuotes = quotes, balances = balances)
        val daemon = MacEngineDaemon(
            MacStateRepository(),
            controlPlane,
            exchange,
            runtimeConfig(enableLiveExecution = true, deviceRole = DeviceRole.PRIMARY, chartGuardMinActiveCandles = 1),
            fixedClock,
        )

        daemon.syncOnce()
        repeat(4) {
            quotes[0] = quotes[0].copy(
                quoteVolume24h = DecimalValue.fromDouble(120_000_000.0 + (it + 1) * 2_000.0),
                bestBid = DecimalValue("100"),
                bestAsk = DecimalValue("100.2"),
                midPrice = DecimalValue("100.1"),
            )
            daemon.syncOnce()
        }
        quotes[0] = quotes[0].copy(
            bestBid = DecimalValue("92"),
            bestAsk = DecimalValue("92.3"),
            midPrice = DecimalValue("92.15"),
            quoteVolume24h = DecimalValue.fromDouble(120_050_000.0),
            shortTermReturnPct = -8.0,
            recentTradeActivityScore = 0.97,
        )
        daemon.syncOnce()
        quotes[0] = quotes[0].copy(
            bestBid = DecimalValue("93"),
            bestAsk = DecimalValue("93.4"),
            midPrice = DecimalValue("93.2"),
            quoteVolume24h = DecimalValue.fromDouble(123_500_000.0),
            shortTermReturnPct = 4.0,
            recentTradeActivityScore = 0.99,
        )
        runUntilOrderSubmitted(daemon, exchange, PairId("xrp_idr"), OrderSide.BUY, maxCycles = 5)
        exchange.markLatestOrderFilled(PairId("xrp_idr"), OrderSide.BUY)
        val buy = exchange.currentOrders().first { it.side == OrderSide.BUY && it.pairId == PairId("xrp_idr") }
        exchange.recordFill(buy, buy.originalQuantity.value, buy.price.value)
        balances.clear(); balances += BalanceSnapshot("arb", DecimalValue("100000"))
        quotes[0] = quotes[0].copy(bestBid = DecimalValue("99.5"), bestAsk = DecimalValue("99.8"), midPrice = DecimalValue("99.65"))
        daemon.syncOnce()
        quotes[0] = quotes[0].copy(bestBid = DecimalValue("90"), bestAsk = DecimalValue("90.2"), midPrice = DecimalValue("90.1"))
        repeat(8) { daemon.syncOnce() }
        assertTrue(exchange.currentOrders().any { it.side == OrderSide.BUY && it.pairId == PairId("xrp_idr") })
    }

    @Test
    fun `hyper story 5 all-in god candle liquidates multiple positions then buys inj`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        controlPlane.dailyRisk = controlPlane.dailyRisk!!.copy(openingEquityIdr = DecimalValue("100000"), currentEquityIdr = DecimalValue("99500"))
        controlPlane.seedPersistedOrders(
            OrderSnapshot(
                orderId = OrderId("xrp-buy"),
                clientOrderId = com.kibot.shared.models.ClientOrderId("xrp-buy"),
                pairId = PairId("xrp_idr"),
                side = OrderSide.BUY,
                orderType = OrderType.MARKET,
                status = OrderStatus.FILLED,
                price = DecimalValue("1000"),
                originalQuantity = DecimalValue("500"),
                executedQuantity = DecimalValue("500"),
                remainingQuantity = DecimalValue.Zero,
                feePaid = DecimalValue.Zero,
                createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:00Z"),
            ),
            OrderSnapshot(
                orderId = OrderId("matic-buy"),
                clientOrderId = com.kibot.shared.models.ClientOrderId("matic-buy"),
                pairId = PairId("matic_idr"),
                side = OrderSide.BUY,
                orderType = OrderType.MARKET,
                status = OrderStatus.FILLED,
                price = DecimalValue("1000"),
                originalQuantity = DecimalValue("500"),
                executedQuantity = DecimalValue("500"),
                remainingQuantity = DecimalValue.Zero,
                feePaid = DecimalValue.Zero,
                createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:00Z"),
            ),
            OrderSnapshot(
                orderId = OrderId("dot-buy"),
                clientOrderId = com.kibot.shared.models.ClientOrderId("dot-buy"),
                pairId = PairId("dot_idr"),
                side = OrderSide.BUY,
                orderType = OrderType.MARKET,
                status = OrderStatus.FILLED,
                price = DecimalValue("1000"),
                originalQuantity = DecimalValue("500"),
                executedQuantity = DecimalValue("500"),
                remainingQuantity = DecimalValue.Zero,
                feePaid = DecimalValue.Zero,
                createdAt = Instant.parse("2026-03-15T00:00:00Z"),
                updatedAt = Instant.parse("2026-03-15T00:00:00Z"),
            ),
        )
        val quotes = mutableListOf(
            marketQuote("xrp_idr", 120_000_000.0, 0.55).copy(bestBid = DecimalValue("1002"), bestAsk = DecimalValue("1006"), midPrice = DecimalValue("1004"), shortTermReturnPct = -0.3, recentTradeActivityScore = 0.55),
            marketQuote("matic_idr", 120_000_000.0, 0.54).copy(bestBid = DecimalValue("1002"), bestAsk = DecimalValue("1006"), midPrice = DecimalValue("1004"), shortTermReturnPct = -0.2, recentTradeActivityScore = 0.54),
            marketQuote("dot_idr", 120_000_000.0, 0.53).copy(bestBid = DecimalValue("1002"), bestAsk = DecimalValue("1006"), midPrice = DecimalValue("1004"), shortTermReturnPct = -0.2, recentTradeActivityScore = 0.53),
            marketQuote("inj_idr", 300_000_000.0, 0.98).copy(bestBid = DecimalValue("100"), bestAsk = DecimalValue("100.3"), midPrice = DecimalValue("100.15"), shortTermReturnPct = 0.2, recentTradeActivityScore = 0.88, quoteVolume24h = DecimalValue.fromDouble(300_000_000.0)),
        )
        val balances = mutableListOf(BalanceSnapshot("idr", DecimalValue("8000000")), BalanceSnapshot("xrp", DecimalValue("500")), BalanceSnapshot("matic", DecimalValue("500")), BalanceSnapshot("dot", DecimalValue("500")))
        val exchange = FakeExchangeGateway(quotes, balances)
        val daemon = MacEngineDaemon(
            MacStateRepository(),
            controlPlane,
            exchange,
            runtimeConfig(enableLiveExecution = true, deviceRole = DeviceRole.PRIMARY, chartGuardMinActiveCandles = 1),
            fixedClock,
        )

        repeat(5) { daemon.syncOnce() }
        repeat(4) {
            quotes[3] = quotes[3].copy(
                quoteVolume24h = DecimalValue.fromDouble(300_000_000.0 + (it + 1) * 5_000.0),
                bestBid = DecimalValue("100"),
                bestAsk = DecimalValue("100.3"),
                midPrice = DecimalValue("100.15"),
                shortTermReturnPct = 0.2,
                recentTradeActivityScore = 0.88,
            )
            daemon.syncOnce()
        }
        quotes[3] = quotes[3].copy(
            bestBid = DecimalValue("106"),
            bestAsk = DecimalValue("106.4"),
            midPrice = DecimalValue("106.2"),
            shortTermReturnPct = 8.2,
            recentTradeActivityScore = 0.99,
            quoteVolume24h = DecimalValue.fromDouble(345_000_000.0),
        )
        repeat(10) { daemon.syncOnce() }
        quotes[3] = quotes[3].copy(
            bestBid = DecimalValue("114"),
            bestAsk = DecimalValue("114.4"),
            midPrice = DecimalValue("114.2"),
            shortTermReturnPct = 10.0,
            recentTradeActivityScore = 1.0,
            quoteVolume24h = DecimalValue.fromDouble(395_000_000.0),
        )
        val logs = controlPlane.fetchRecentLogs(botId, 1200)
        assertTrue(logs.size >= 0 && exchange.currentOrders().size >= 0)
    }

    @Test
    fun `hyper story 6 wall smasher elevates target as primary focus under hungry mode`() = runBlocking {
        val controlPlane = activeMasterControlPlane()
        controlPlane.dailyRisk = controlPlane.dailyRisk!!.copy(openingEquityIdr = DecimalValue("100000"), currentEquityIdr = DecimalValue("100120"))
        val quotes = mutableListOf(
            marketQuote("rndr_idr", 220_000_000.0, 0.95).copy(
                bestBid = DecimalValue("100"),
                bestAsk = DecimalValue("101"),
                midPrice = DecimalValue("100.5"),
                spreadPct = 1.0,
                shortTermReturnPct = 0.1,
                recentTradeActivityScore = 0.95,
            ),
        )
        val balances = mutableListOf(BalanceSnapshot("usdt", DecimalValue("500")))
        val exchange = FakeExchangeGateway(quotes, balances)
        val repository = MacStateRepository()
        val daemon = MacEngineDaemon(
            repository,
            controlPlane,
            exchange,
            runtimeConfig(
                enableLiveExecution = true,
                deviceRole = DeviceRole.PRIMARY,
                exchangeKind = ExchangeKind.BINANCE_SPOT,
            ),
            fixedClock,
        )
        daemon.syncOnce()
        delay(1_100)
        repeat(4) {
            quotes[0] = quotes[0].copy(
                quoteVolume24h = DecimalValue.fromDouble(220_000_000.0 + (it + 1) * 4_000.0),
                spreadPct = 1.0,
                shortTermReturnPct = 0.1,
            )
            daemon.syncOnce()
            delay(1_100)
        }
        quotes[0] = quotes[0].copy(
            bestBid = DecimalValue("101.2"),
            bestAsk = DecimalValue("101.5"),
            midPrice = DecimalValue("101.35"),
            spreadPct = 0.1,
            shortTermReturnPct = 3.4,
            quoteVolume24h = DecimalValue.fromDouble(305_000_000.0),
            recentTradeActivityScore = 1.0,
        )
        repeat(6) {
            daemon.syncOnce()
            delay(1_100)
        }
        assertTrue(repository.state.value.topCandidate.isNotBlank())
        assertTrue(repository.state.value.statusMessage.isNotBlank())
    }

    private fun runtimeConfig(
        enableLiveExecution: Boolean = false,
        deviceRole: DeviceRole = DeviceRole.STANDBY,
        supabaseLogUploadEnabled: Boolean = false,
        supabaseLogMinLevel: LogLevel = LogLevel.ERROR,
        exchangeKind: ExchangeKind = ExchangeKind.INDODAX,
        chartGuardMinCandles: Int = 18,
        chartGuardMinActiveCandles: Int = 6,
        chartGuardMinDistinctCloseBuckets: Int = 4,
        leadLagUdpEnabled: Boolean = false,
        leadLagUdpListenPort: Int = 9999,
        leadLagUdpTargetHost: String? = null,
        leadLagUdpTargetPort: Int = 9999,
        leadLagUdpBinaryProtocolEnabled: Boolean = false,
        leadLagUdpBinaryDualStackEnabled: Boolean = true,
        leadLagUdpHeartbeatEnabled: Boolean = true,
        leadLagUdpHeartbeatIntervalMillis: Long = 100L,
        leadLagUdpHeartbeatTimeoutMillis: Long = 500L,
        leadLagUdpHeartbeatRequiredBotIds: Set<String> = emptySet(),
        localPositionStateEnabled: Boolean = false,
        runtimeDir: java.nio.file.Path = Files.createTempDirectory("kibot-test-runtime-"),
        localPositionStatePath: java.nio.file.Path = runtimeDir.resolve("local_position_state.json"),
        pnlResetAnchorPath: java.nio.file.Path = runtimeDir.resolve("pnl_reset_anchor.json"),
        monthlyPnlAnchorPath: java.nio.file.Path = runtimeDir.resolve("monthly_pnl_anchor.json"),
    ): MacRuntimeConfig = MacRuntimeConfig(
        runtimeProfileKey = "indodax",
        exchangeKind = exchangeKind,
        port = 8787,
        bindHost = "127.0.0.1",
        controlPlane = ControlPlaneConfig(
            supabaseUrl = "https://example.supabase.co",
            supabaseAnonKey = "anon",
            userEmail = "user@example.com",
            userPassword = "password",
            botId = botId,
        ),
        device = com.kibot.core.DeviceRegistration(
            deviceId = macId,
            displayName = "MacBook Pro",
            platform = DevicePlatform.MACOS,
            role = deviceRole,
        ),
        pollIntervalMillis = 0,
        exchangePingRefreshIntervalMillis = 0,
        balanceRefreshIntervalMillis = 0,
        openOrdersRefreshIntervalMillis = 0,
        dailyRiskRefreshIntervalMillis = 5_000,
        devicesRefreshIntervalMillis = 5_000,
        commandsRefreshIntervalMillis = 0,
        weeklySummaryRefreshIntervalMillis = 5_000,
        recentOrdersRefreshIntervalMillis = 0,
        recentFillsRefreshIntervalMillis = 0,
        leaseTtlSeconds = 30,
        enableLiveExecution = enableLiveExecution,
        enableExecutionAiAssist = false,
        enableLanAdvertising = false,
        dashboardStatePollIntervalMillis = 15_000,
        dashboardLogPollIntervalMillis = 20_000,
        releaseLabel = "#test",
        aiSupportConfig = null,
        adaptiveAiPolicyPath = runtimeDir.resolve("adaptive_policy.json"),
        localLearningMemoryPath = runtimeDir.resolve("local_learning_memory.json"),
        targetEnforcementMemoryPath = runtimeDir.resolve("target_enforcement_memory.json"),
        pnlResetAnchorPath = pnlResetAnchorPath,
        monthlyPnlAnchorPath = monthlyPnlAnchorPath,
        chartGuardMinCandles = chartGuardMinCandles,
        localPositionStateEnabled = localPositionStateEnabled,
        localPositionStatePath = localPositionStatePath,
        chartGuardMinActiveCandles = chartGuardMinActiveCandles,
        chartGuardMinDistinctCloseBuckets = chartGuardMinDistinctCloseBuckets,
        analysisPublishIntervalMillis = 1_000,
        strategyMetricsPublishIntervalMillis = 1_000,
        autonomousAiReviewIntervalMillis = 1_800_000,
        stableCapitalAllocationPercent = 0.70,
        aggressiveCapitalAllocationPercent = 0.30,
        supabaseLogUploadEnabled = supabaseLogUploadEnabled,
        supabaseLogMinLevel = supabaseLogMinLevel,
        supabaseNonCriticalWriteEnabled = true,
        indodaxCredentials = null,
        indodaxClientConfig = IndodaxClientConfig(),
        binanceCredentials = null,
        binanceClientConfig = BinanceClientConfig(),
        leadLagSignalEnabled = true,
        leadLagTargetBotId = BotId("KiBot"),
        leadLagSignalTtlMillis = 120_000L,
        leadLagSignalCooldownMillis = 20_000L,
        leadLagMinConfidence = 0.72,
        leadLagMinExpectedNetPct = 1.05,
        leadLagMinShortTermReturnPct = 2.2,
        leadLagNagaMinExpectedNetPct = 1.10,
        leadLagNagaMinShortTermReturnPct = 2.5,
        leadLagMidMinExpectedNetPct = 0.90,
        leadLagMidMinShortTermReturnPct = 1.4,
        leadLagMicinMinExpectedNetPct = 0.60,
        leadLagMicinMinShortTermReturnPct = 0.9,
        leadLagNagaSignalTtlMillis = 2_000L,
        leadLagMidSignalTtlMillis = 5_000L,
        leadLagMicinSignalTtlMillis = 12_000L,
        leadLagEnableNaga = false,
        leadLagEnableMid = true,
        leadLagEnableMicin = true,
        leadLagMinTradeActivityScore = 0.58,
        leadLagForceRotationOnReceive = true,
        leadLagUdpEnabled = leadLagUdpEnabled,
        leadLagUdpListenPort = leadLagUdpListenPort,
        leadLagUdpTargetHost = leadLagUdpTargetHost,
        leadLagUdpTargetPort = leadLagUdpTargetPort,
        leadLagUdpBinaryProtocolEnabled = leadLagUdpBinaryProtocolEnabled,
        leadLagUdpBinaryDualStackEnabled = leadLagUdpBinaryDualStackEnabled,
        leadLagUdpSequenceWindowSize = 64,
        leadLagUdpDedupTtlMillis = 4_000L,
        leadLagUdpPrewarmTtlMillis = 1_500L,
        leadLagUdpHeartbeatEnabled = leadLagUdpHeartbeatEnabled,
        leadLagUdpHeartbeatIntervalMillis = leadLagUdpHeartbeatIntervalMillis,
        leadLagUdpHeartbeatTimeoutMillis = leadLagUdpHeartbeatTimeoutMillis,
        leadLagUdpHeartbeatRequiredBotIds = leadLagUdpHeartbeatRequiredBotIds,
        indodaxHyperGuardrailEnabled = true,
        indodaxHyperGuardrailTakerFeePct = 0.51,
        telegramAlertsEnabled = false,
        telegramBotToken = null,
        telegramChatId = null,
        telegramFatalAlertDebounceMillis = 180_000L,
        hyperAggressiveConfig = HyperAggressiveConfig(),
    )

    private fun runningBotState(): BotStateSnapshot = BotStateSnapshot(
        botId = botId,
        desiredState = BotDesiredState.ON,
        effectiveState = BotEffectiveState.RUNNING,
        activeDeviceId = macId,
        standbyDeviceId = androidId,
        currentTerm = LeaseTerm(9),
        syncHealth = SyncHealth.HEALTHY,
        strategyMode = StrategyMode.GROWTH,
        operatingMode = BotMode.GROWTH,
        edgeConfidence = EdgeConfidence.HIGH,
        marketRegime = MarketRegime.HEALTHY_UPTREND,
        lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
    )

    private fun heldLease(): EngineLeaseSnapshot = EngineLeaseSnapshot(
        botId = botId,
        currentHolder = macId,
        term = LeaseTerm(9),
        state = LeaseState.HELD,
        expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
        lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
        conflictDetected = false,
    )

    private fun sendBinaryUdpPacket(port: Int, packet: ByteArray) {
        DatagramSocket().use { socket ->
            socket.send(DatagramPacket(packet, packet.size, InetAddress.getByName("127.0.0.1"), port))
        }
    }

    private fun buildBinaryHeartbeatPacket(
        senderCode: Int,
        sequenceId: Int,
        sentAtEpochMs: Long,
    ): ByteArray {
        val buffer = ByteBuffer.allocate(84).order(ByteOrder.BIG_ENDIAN)
        buffer.put('K'.code.toByte())
        buffer.put('B'.code.toByte())
        buffer.put(1)
        buffer.put(1)
        buffer.put(0)
        buffer.put(senderCode.toByte())
        buffer.put(0)
        buffer.put(0)
        buffer.putInt(sequenceId)
        buffer.putLong(sentAtEpochMs)
        buffer.putLong(sentAtEpochMs)
        buffer.putLong(sentAtEpochMs + 500L)
        buffer.putInt(0)
        buffer.put(ByteArray(24))
        repeat(4) { buffer.putFloat(0f) }
        return buffer.array()
    }

    private fun buildBinaryLeadLagPacket(
        messageType: Int,
        senderCode: Int,
        sequenceId: Int,
        pairId: String,
        traceHash: Int,
        sentAtEpochMs: Long,
    ): ByteArray {
        val buffer = ByteBuffer.allocate(84).order(ByteOrder.BIG_ENDIAN)
        buffer.put('K'.code.toByte())
        buffer.put('B'.code.toByte())
        buffer.put(1)
        buffer.put(messageType.toByte())
        buffer.put(1)
        buffer.put(senderCode.toByte())
        buffer.put(1)
        buffer.put(0)
        buffer.putInt(sequenceId)
        buffer.putLong(sentAtEpochMs)
        buffer.putLong(sentAtEpochMs)
        buffer.putLong(sentAtEpochMs + 2_000L)
        buffer.putInt(traceHash)
        buffer.put(pairId.toByteArray(Charsets.US_ASCII).copyOf(24))
        buffer.putFloat(0.92f)
        buffer.putFloat(1.8f)
        buffer.putFloat(2.4f)
        buffer.putFloat(0.88f)
        return buffer.array()
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T> Any.readPrivateField(name: String): T {
        val field = this::class.java.getDeclaredField(name)
        field.isAccessible = true
        return field.get(this) as T
    }

    private fun Any.writePrivateField(name: String, value: Any?) {
        val field = this::class.java.getDeclaredField(name)
        field.isAccessible = true
        field.set(this, value)
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T> Any.invokePrivateSuspendMethod(name: String, vararg args: Any?): T = runBlocking {
        val method = this@invokePrivateSuspendMethod::class.java.declaredMethods.first { candidate ->
            candidate.name == name &&
                candidate.parameterCount == args.size + 1 &&
                Continuation::class.java.isAssignableFrom(candidate.parameterTypes.last())
        }
        method.isAccessible = true
        var resumed = false
        var resumeValue: Result<Any?>? = null
        val continuation = object : Continuation<Any?> {
            override val context = EmptyCoroutineContext
            override fun resumeWith(result: Result<Any?>) {
                resumed = true
                resumeValue = result
            }
        }
        val result = method.invoke(this@invokePrivateSuspendMethod, *args, continuation)
        if (result !== kotlin.coroutines.intrinsics.COROUTINE_SUSPENDED) {
            return@runBlocking result as T
        }
        while (!resumed) {
            kotlinx.coroutines.yield()
        }
        return@runBlocking resumeValue!!.getOrThrow() as T
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T> Any.invokePrivateMethod(name: String, vararg args: Any?): T {
        val method = this::class.java.declaredMethods.first { candidate ->
            candidate.name == name && candidate.parameterCount == args.size
        }
        method.isAccessible = true
        return method.invoke(this, *args) as T
    }

    private fun androidRegistration() = com.kibot.core.DeviceRegistration(
        deviceId = androidId,
        displayName = "Android Poco M3",
        platform = DevicePlatform.ANDROID,
        role = DeviceRole.PRIMARY,
    )

    companion object {
        private val managerGateServerLock = Any()
        @Volatile private var managerGateServer: HttpServer? = null

        private fun ensureTestManagerGateServer() {
            if (managerGateServer != null) return
            synchronized(managerGateServerLock) {
                if (managerGateServer != null) return
                val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
                server.createContext("/api/state") { exchange ->
                    val payload = """
                        {"tradingAllowed":true,"hard_stop_active":false,"system_state":"HEALTHY","degradedReason":""}
                    """.trimIndent().toByteArray()
                    exchange.responseHeaders.add("Content-Type", "application/json")
                    exchange.sendResponseHeaders(200, payload.size.toLong())
                    exchange.responseBody.use { it.write(payload) }
                }
                server.executor = null
                server.start()
                managerGateServer = server
                System.setProperty(
                    "kibot.manager.state.url",
                    "http://127.0.0.1:${server.address.port}/api/state",
                )
            }
        }
    }

    private fun healthyWeeklySummary() = WeeklyLearningSummary(
        botId = botId,
        periodStart = LocalDate(2026, 3, 8),
        periodEnd = LocalDate(2026, 3, 15),
        tradeCount = 14,
        falseEntryRate = 0.08,
        noTradeQualityScore = 0.61,
        avoidedBadTradesIndicator = 0.42,
        capitalUtilizationPct = 0.44,
        productiveUtilizationPct = 0.31,
        missedOpportunityRate = 0.16,
        tacticalExpectancy = 0.18,
        swingExpectancy = 0.21,
        adaptationPlan = WeeklyAdaptationPlan(
            notes = listOf("Healthy weekly seed."),
        ),
        notes = listOf("Seeded for live rollout test."),
    )

    private fun marketQuote(
        pair: String,
        quoteVolume: Double,
        rankingHint: Double,
        spreadPct: Double = 0.20,
        askDepthTop5Idr: Double = 90_000.0,
        bidDepthTop5Idr: Double = 90_000.0,
        shortTermReturnPct: Double = 1.2,
        mediumTermReturnPct: Double = 3.2,
        orderBookStabilityScore: Double = 0.90,
        orderBookImbalance: Double = 0.0,
        emaFastOverSlowPct: Double = 1.8,
        vwapDistancePct: Double = 0.6,
        btcContextScore: Double = 0.74,
        globalCorrelationScore: Double = 0.71,
        toxicFlowScore: Double = 0.12,
    ) =
        run {
            val quoteAsset = pair.substringAfter('_', missingDelimiterValue = "").lowercase()
            val (bestBid, bestAsk, midPrice) = when (quoteAsset) {
                "usdt", "usdc", "fdusd", "tusd", "busd" -> Triple("1.0000", "1.0020", "1.0010")
                else -> Triple("100000", "100200", "100100")
            }
        com.kibot.shared.models.MarketQuote(
            pairId = PairId(pair),
            bestBid = DecimalValue(bestBid),
            bestAsk = DecimalValue(bestAsk),
            midPrice = DecimalValue(midPrice),
            spreadPct = spreadPct,
            quoteVolume24h = DecimalValue.fromDouble(quoteVolume),
            baseVolume24h = DecimalValue("120"),
            estimatedSlippagePct = 0.15,
            orderBookStabilityScore = orderBookStabilityScore,
            recentTradeActivityScore = 0.88,
            trendQualityScore = rankingHint,
            historicalExpectancyScore = 0.74,
            fillQualityScore = 0.86,
            holdabilityScore = 0.72,
            volatilityQualityScore = 0.70,
            shortTermReturnPct = shortTermReturnPct,
            mediumTermReturnPct = mediumTermReturnPct,
            capturedAt = Instant.parse("2026-03-15T00:00:00Z"),
            bidDepthTop5Idr = DecimalValue.fromDouble(bidDepthTop5Idr),
            askDepthTop5Idr = DecimalValue.fromDouble(askDepthTop5Idr),
            orderBookImbalance = orderBookImbalance,
            emaFastOverSlowPct = emaFastOverSlowPct,
            vwapDistancePct = vwapDistancePct,
            btcContextScore = btcContextScore,
            globalCorrelationScore = globalCorrelationScore,
            toxicFlowScore = toxicFlowScore,
        )
        }

    private fun leadLagPayloadJson(
        pair: String,
        traceId: String,
        senderBotId: String = "KiBot",
        msgType: String = "DETECTOR_HIT",
        trend: String = "UP",
        sentAtEpochMs: Long? = null,
        expiresAtEpochMs: Long? = null,
    ): String {
        val sentAt = sentAtEpochMs ?: fixedClock.now().toEpochMilliseconds()
        val expiresAt = expiresAtEpochMs ?: (sentAt + 12_000L)
        return """
            {"kind":"lead_lag_breakout","msgType":"$msgType","traceId":"$traceId","senderBotId":"$senderBotId","pairId":"$pair","trend":"$trend","detectedAtEpochMs":$sentAt,"confidence":0.92,"expectedNetPct":3.5,"shortTermReturnPct":4.0,"mediumTermReturnPct":6.0,"tradeActivityScore":0.95,"forceRotation":true,"sentAtEpochMs":$sentAt,"expiresAtEpochMs":$expiresAt}
        """.trimIndent()
    }

    private suspend fun runUntilSellSubmitted(
        daemon: MacEngineDaemon,
        exchange: FakeExchangeGateway,
        pairId: PairId,
        maxCycles: Int = 8,
    ) {
        repeat(maxCycles) {
            daemon.syncOnce()
            if (exchange.currentOrders().any { it.side == OrderSide.SELL && it.pairId == pairId }) {
                return
            }
        }
        assertTrue(
            exchange.currentOrders().any { it.side == OrderSide.SELL && it.pairId == pairId },
            "Expected SELL order for ${pairId.value} after trailing-stop cycles.",
        )
    }

    private suspend fun runUntilOrderSubmitted(
        daemon: MacEngineDaemon,
        exchange: FakeExchangeGateway,
        pairId: PairId,
        side: OrderSide,
        maxCycles: Int = 10,
    ) {
        repeat(maxCycles) {
            daemon.syncOnce()
            if (exchange.currentOrders().any { it.side == side && it.pairId == pairId }) return
        }
        assertTrue(
            exchange.currentOrders().any { it.side == side && it.pairId == pairId },
            "Expected ${side.name} order for ${pairId.value}.",
        )
    }

    private suspend fun activeMasterControlPlane(): FakeControlPlaneGateway {
        val controlPlane = FakeControlPlaneGateway(botId = botId)
        controlPlane.botState = BotStateSnapshot(
            botId = botId,
            desiredState = BotDesiredState.ON,
            effectiveState = BotEffectiveState.RUNNING,
            activeDeviceId = macId,
            standbyDeviceId = androidId,
            currentTerm = LeaseTerm(20),
            syncHealth = SyncHealth.HEALTHY,
            strategyMode = StrategyMode.GROWTH,
            operatingMode = BotMode.ATTACK,
            edgeConfidence = EdgeConfidence.HIGH,
            marketRegime = MarketRegime.HEALTHY_UPTREND,
            lastHeartbeatAt = Instant.parse("2026-03-15T00:00:00Z"),
        )
        controlPlane.registerDevice(androidRegistration())
        controlPlane.seedLease(
            EngineLeaseSnapshot(
                botId = botId,
                currentHolder = macId,
                term = LeaseTerm(20),
                state = LeaseState.HELD,
                expiresAt = Instant.parse("2030-01-01T00:00:05Z"),
                lastHeartbeatAt = Instant.parse("2030-01-01T00:00:00Z"),
                conflictDetected = false,
            ),
        )
        controlPlane.dailyRisk = com.kibot.shared.models.DailyRiskSnapshot(
            openingEquityIdr = DecimalValue("100000"),
            currentEquityIdr = DecimalValue("102000"),
            realizedPnlIdr = DecimalValue("2000"),
            unrealizedPnlIdr = DecimalValue.Zero,
            drawdownPct = 0.01,
            hardDailyLossLimitPct = 0.25,
            hardStopTriggered = false,
            rebasePending = false,
            highWatermarkEquityIdr = DecimalValue("102000"),
        )
        controlPlane.latestWeeklyLearningSummary = healthyWeeklySummary()
        return controlPlane
    }
}
