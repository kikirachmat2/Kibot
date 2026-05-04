package com.kibot.macengine.server

import com.kibot.macengine.runtime.MacCommandDispatcher
import com.kibot.macengine.state.MacDashboardState
import com.kibot.macengine.state.MacCommand
import com.kibot.macengine.state.MacStateRepository
import com.kibot.macengine.runtime.MacEngineDaemon
import com.kibot.shared.models.BotId
import com.kibot.shared.models.BotDesiredState
import com.kibot.shared.models.CommandCenterCommandReply
import com.kibot.shared.models.CommandCenterCommandRequest
import com.kibot.shared.models.CommandCenterLiveSnapshot
import com.kibot.shared.models.CommandCenterTimelineEntry
import com.kibot.shared.models.CommandCenterHolding
import com.kibot.shared.models.CommandCenterOrder
import com.kibot.shared.models.CommandCenterWsEnvelope
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.call
import io.ktor.server.application.install
import io.ktor.server.cio.CIO
import io.ktor.server.engine.embeddedServer
import io.ktor.server.html.respondHtml
import io.ktor.server.plugins.calllogging.CallLogging
import io.ktor.server.plugins.contentnegotiation.ContentNegotiation
import io.ktor.server.plugins.statuspages.StatusPages
import io.ktor.server.request.uri
import io.ktor.server.response.header
import io.ktor.server.response.respond
import io.ktor.server.response.respondFile
import io.ktor.server.response.respondText
import io.ktor.server.response.respondTextWriter
import io.ktor.server.request.header
import io.ktor.server.routing.get
import io.ktor.server.routing.post
import io.ktor.server.routing.routing
import io.ktor.server.websocket.WebSockets
import io.ktor.server.websocket.webSocket
import io.ktor.serialization.kotlinx.json.json
import io.ktor.websocket.Frame
import io.ktor.websocket.close
import io.ktor.websocket.readText
import io.ktor.websocket.send
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.html.BODY
import kotlinx.html.FlowContent
import kotlinx.html.button
import kotlinx.html.body
import kotlinx.html.div
import kotlinx.html.h1
import kotlinx.html.h2
import kotlinx.html.head
import kotlinx.html.meta
import kotlinx.html.p
import kotlinx.html.script
import kotlinx.html.span
import kotlinx.html.strong
import kotlinx.html.style
import kotlinx.html.title
import kotlinx.html.unsafe
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.decodeFromString
import java.io.EOFException
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.nio.channels.ClosedChannelException
import java.util.Collections
import java.net.NetworkInterface
import java.util.concurrent.CancellationException
import org.slf4j.LoggerFactory

class LocalDashboardServer(
    private val repository: MacStateRepository,
    private val commandDispatcher: MacCommandDispatcher? = null,
    private val botId: BotId = BotId("main"),
    private val host: String = "0.0.0.0",
    private val port: Int = 8787,
    private val androidReleaseDirectory: Path,
    private val enableLanAdvertising: Boolean = true,
    private val statePollIntervalMillis: Long = 2_000L,
    private val logPollIntervalMillis: Long = 5_000L,
) {
    @Serializable
    private data class MobileStateResponse(
        val timestamp: Long,
        val portfolioIdr: String,
        val pnl: String,
        val active: Int,
        val status: String,
    )

    @Serializable
    private data class DashboardConnectionStatus(val status: String, val latencyMs: Int)

    @Serializable
    private data class DashboardConnections(val KiBot: DashboardConnectionStatus, val KiBot: DashboardConnectionStatus)

    @Serializable
    private data class ActivePositionState(val pair: String, val currentPrice: String, val pnlPct: String, val pnlIdr: String, val size: String)

    @Serializable
    private data class PairScoreState(val pair: String)

    @Serializable
    private data class HealthServicesResponse(
        val KiBot: String,
        val kibot: String,
        val KiBot: String,
    )

    @Serializable
    private data class HealthResponse(
        val status: String,
        val timestamp: String,
        val uptimeMs: Long,
        val botId: String,
        val effectiveState: String,
        val syncHealth: String,
        val tradingAllowed: Boolean,
        val hardStopActive: Boolean,
        val services: HealthServicesResponse,
    )

    @Serializable
    private data class DashboardStateResponse(
        val portfolioValueIdr: String,
        val dailyPnlPct: Double,
        val dailyPnlIdr: Double,
        val tradingAllowed: Boolean,
        val hardStopActive: Boolean,
        val botMode: String,
        val lastUpdate: String,
        val connections: DashboardConnections,
        val activePositions: List<ActivePositionState>,
        val pairScores: List<PairScoreState>,
        val learningState: JsonObject,
        val whatIfSimulation: JsonElement,
        val tradeHistory: JsonElement,
        val rawState: JsonElement,
        val stale: Boolean = false,
        val cacheAgeMs: Long = 0L,
    )

    private val logger = LoggerFactory.getLogger(LocalDashboardServer::class.java)
    private val startedAtMs = System.currentTimeMillis()
    private val lanProbeUrl = detectLanProbeUrl(host, port)
    private val lanServiceAdvertiser = if (enableLanAdvertising) LanServiceAdvertiser(host, port) else null
    private val commandAuth = DashboardCommandAuth.fromEnv(host)
    private val relaxedJson = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }
    private val stateCacheScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    @Volatile private var stateCacheJob: kotlinx.coroutines.Job? = null
    @Volatile private var cachedStateResponse: DashboardStateResponse? = null
    @Volatile private var cachedStateUpdatedAtMs: Long = 0L

    private val server = embeddedServer(CIO, host = host, port = port) {
        install(CallLogging)
        install(ContentNegotiation) { json() }
        install(WebSockets)
        install(StatusPages) {
            exception<Throwable> { call, cause ->
                if (isBenignClientDisconnect(cause)) {
                    logger.debug("Ignoring benign disconnect on ${call.request.uri}: ${cause.message}")
                    return@exception
                }
                call.respond(HttpStatusCode.InternalServerError, mapOf("error" to (cause.message ?: "unknown")))
            }
        }

        routing {
            // Modern full-screen dashboard
            get("/dashboard") {
                applyDashboardSecurityHeaders(call)
                val dashboardHtml = this::class.java.classLoader.getResourceAsStream("dashboard.html")?.readBytes()?.decodeToString()
                if (dashboardHtml != null) {
                    call.respondText(dashboardHtml, ContentType.Text.Html)
                } else {
                    call.respondText("Dashboard not found", ContentType.Text.Plain, HttpStatusCode.NotFound)
                }
            }

            get("/") {
                applyDashboardSecurityHeaders(call)
                val dashboardHtml = MacEngineDaemon::class.java.classLoader.getResourceAsStream("dashboard.html")?.readBytes()?.decodeToString()
                if (dashboardHtml != null) {
                    call.respondText(dashboardHtml, ContentType.Text.Html)
                } else {
                    call.respondText("Dashboard not found", ContentType.Text.Plain, HttpStatusCode.NotFound)
                }
            }

            get("/api/state") {
                applyDashboardSecurityHeaders(call)
                val now = System.currentTimeMillis()
                val freshCache = cachedStateResponse
                val cacheAgeMs = now - cachedStateUpdatedAtMs
                if (freshCache != null && cacheAgeMs <= statePollIntervalMillis.coerceAtLeast(1_000L)) {
                    call.respond(freshCache.copy(stale = false, cacheAgeMs = cacheAgeMs.coerceAtLeast(0L)))
                } else {
                    val rebuilt = buildDashboardStateResponse()
                    cachedStateResponse = rebuilt
                    cachedStateUpdatedAtMs = now
                    call.respond(rebuilt.copy(stale = false, cacheAgeMs = 0L))
                }
            }

            get("/api/health") {
                applyDashboardSecurityHeaders(call)
                val state = repository.state.value
                val dailyPnlPct = state.pnlTodayPctLabel
                    .replace("%", "")
                    .replace("+", "")
                    .toDoubleOrNull()
                val safeModeActive = state.effectiveState.name == "SAFE_MODE"
                val tradingAllowed = state.liveExecutionEnabled && !safeModeActive
                val dailyLossHardStop = tradingAllowed.not() && (dailyPnlPct ?: 0.0) <= -3.0
                val hardStopActive =
                    safeModeActive ||
                    state.statusMessage.contains("hard stop", ignoreCase = true) ||
                        state.healthSummary.contains("hard stop", ignoreCase = true) ||
                        state.healthSummary.contains("daily_loss_limit", ignoreCase = true) ||
                        dailyLossHardStop
                val safeOnly = hardStopActive || state.effectiveState.name == "SAFE_MODE"
                val degraded = state.effectiveState.name == "STOPPED" ||
                    state.syncHealth.equals("BROKEN", ignoreCase = true) ||
                    (state.statusMessage.contains("safe mode", ignoreCase = true) && !safeOnly)
                val payload = HealthResponse(
                    status = when {
                        safeOnly -> "safe"
                        degraded -> "degraded"
                        else -> "ok"
                    },
                    timestamp = java.time.Instant.now().toString(),
                    uptimeMs = (System.currentTimeMillis() - startedAtMs),
                    botId = botId.value,
                    effectiveState = state.effectiveState.name,
                    syncHealth = state.syncHealth,
                    tradingAllowed = tradingAllowed,
                    hardStopActive = hardStopActive,
                    services = HealthServicesResponse(
                        KiBot = state.KiBotNodeStatus,
                        kibot = state.kibotNodeStatus,
                        KiBot = state.KiBotNodeStatus,
                    ),
                )
                call.respond(if (degraded) HttpStatusCode.ServiceUnavailable else HttpStatusCode.OK, payload)
            }
            
            get("/api/trade-history") {
                applyDashboardSecurityHeaders(call)
                val days = call.request.queryParameters["days"]?.toIntOrNull() ?: 7
                val trades = when (days) {
                    1 -> com.kibot.macengine.logging.TradeLogger.getTodayTrades()
                    7 -> com.kibot.macengine.logging.TradeLogger.getLast7DaysTrades()
                    20, 30 -> com.kibot.macengine.logging.TradeLogger.getLast30DaysTrades()
                    else -> com.kibot.macengine.logging.TradeLogger.getLast7DaysTrades()
                }
                call.respond(trades)
            }

            get("/api/trade-history/today") {
                applyDashboardSecurityHeaders(call)
                val trades = com.kibot.macengine.logging.TradeLogger.getTodayTrades()
                call.respond(trades)
            }
            
            get("/api/mobile") {
                applyDashboardSecurityHeaders(call)
                val state = repository.state.value
                val safeModeActive = state.effectiveState.name == "SAFE_MODE"
                val compact = MobileStateResponse(
                    timestamp = java.time.Instant.now().epochSecond,
                    portfolioIdr = state.portfolioValueIdr,
                    pnl = state.pnlTodayIdr,
                    active = state.holdingsDetailed.size,
                    status = if (state.liveExecutionEnabled && !safeModeActive) "LIVE" else "PAUSED"
                )
                call.respond(compact)
            }

            get("/api/state/stream") {
                applyDashboardSecurityHeaders(call, cacheControl = "no-store, no-cache, must-revalidate, max-age=0")
                call.response.header("Connection", "keep-alive")
                call.respondTextWriter(ContentType.Text.EventStream) {
                    try {
                        write(": kibot-state-stream\n\n")
                        flush()
                        repository.state.collect { latest ->
                            if (!isActive) return@collect
                            runCatching {
                                val payload = Json.encodeToString(latest)
                                write("event: state\n")
                                write("data: $payload\n\n")
                                flush()
                            }.onFailure { error ->
                                logger.error("SSE state stream failed: ${error.message}")
                            }
                        }
                    } catch (error: Throwable) {
                        if (isBenignClientDisconnect(error)) {
                            logger.debug("State stream closed by client: ${error.message}")
                        } else {
                            throw error
                        }
                    }
                }
            }

            get("/favicon.png") {
                applyDashboardSecurityHeaders(call, cacheControl = "public, max-age=3600")
                val icon = locateDashboardIcon()
                if (icon == null) {
                    call.respond(HttpStatusCode.NotFound, mapOf("available" to false))
                } else {
                    call.respondFile(icon)
                }
            }

            webSocket("/api/live/ws") {
                if (!commandAuth.allowSession(call)) {
                    close(io.ktor.websocket.CloseReason(io.ktor.websocket.CloseReason.Codes.VIOLATED_POLICY, "unauthorized"))
                    return@webSocket
                }
                val limiter = DashboardCommandRateLimiter()
                val snapshot = repository.state.value.toLiveSnapshot(host, port, botId)
                send(
                    Json.encodeToString(
                        CommandCenterWsEnvelope.Snapshot(snapshot),
                    ),
                )
                val job = launch {
                    repository.state.collect { latest ->
                        if (!isActive) return@collect
                        runCatching {
                            val snapshot = latest.toLiveSnapshot(host, port, botId)
                            send(Json.encodeToString(CommandCenterWsEnvelope.Snapshot(snapshot)))
                        }.onFailure { error ->
                            logger.error("WebSocket broadcast failed: ${error.message}")
                        }
                    }
                }
                try {
                    for (frame in incoming) {
                        val text = (frame as? Frame.Text)?.readText() ?: continue
                        if (!limiter.allow()) {
                            close(
                                io.ktor.websocket.CloseReason(
                                    io.ktor.websocket.CloseReason.Codes.TRY_AGAIN_LATER,
                                    "rate_limited",
                                ),
                            )
                            return@webSocket
                        }
                        val request = runCatching {
                            Json.decodeFromString<CommandCenterCommandRequest>(text)
                        }.getOrNull() ?: continue
                        val reply = handleCommandRequest(request)
                        send(Json.encodeToString(CommandCenterWsEnvelope.Reply(reply)))
                    }
                } finally {
                    job.cancel()
                }
            }

            // WebSocket alias for Android app compatibility
            webSocket("/ws") {
                if (!commandAuth.allowSession(call)) {
                    close(io.ktor.websocket.CloseReason(io.ktor.websocket.CloseReason.Codes.VIOLATED_POLICY, "unauthorized"))
                    return@webSocket
                }
                val limiter = DashboardCommandRateLimiter()
                send(
                    Json.encodeToString(
                        CommandCenterWsEnvelope.Snapshot(repository.state.value.toLiveSnapshot(host, port, botId)),
                    ),
                )
                val job = launch {
                    repository.state.collect { latest ->
                        if (!isActive) return@collect
                        runCatching {
                            val snapshot = latest.toLiveSnapshot(host, port, botId)
                            send(Json.encodeToString(CommandCenterWsEnvelope.Snapshot(snapshot)))
                        }.onFailure { error ->
                            logger.error("Legacy WebSocket broadcast failed: ${error.message}")
                        }
                    }
                }
                try {
                    for (frame in incoming) {
                        val text = (frame as? Frame.Text)?.readText() ?: continue
                        if (!limiter.allow()) {
                            close(
                                io.ktor.websocket.CloseReason(
                                    io.ktor.websocket.CloseReason.Codes.TRY_AGAIN_LATER,
                                    "rate_limited",
                                ),
                            )
                            return@webSocket
                        }
                        val request = runCatching {
                            Json.decodeFromString<CommandCenterCommandRequest>(text)
                        }.getOrNull() ?: continue
                        val reply = handleCommandRequest(request)
                        send(Json.encodeToString(CommandCenterWsEnvelope.Reply(reply)))
                    }
                } finally {
                    job.cancel()
                }
            }

            get("/api/logs") {
                applyDashboardSecurityHeaders(call)
                val freshCutoff = System.currentTimeMillis() - WEB_LOG_FRESHNESS_WINDOW_MS
                call.respond(
                    repository.state.value.liveTimeline
                        .filter { it.timestampEpochMs <= 0L || it.timestampEpochMs >= freshCutoff }
                        .sortedByDescending { it.timestampEpochMs }
                        .map { "${it.category} • ${it.message}" },
                )
            }

            get("/api/lan/ping") {
                applyDashboardSecurityHeaders(call)
                call.respond(LanPingResponse(ok = true, host = host, port = port, lanProbeUrl = lanProbeUrl))
            }

            get("/api/releases/android/latest") {
                applyDashboardSecurityHeaders(call, cacheControl = "no-store, max-age=0")
                val manifestPath = androidReleaseDirectory.resolve("latest.json")
                if (!Files.exists(manifestPath)) {
                    call.respond(HttpStatusCode.NotFound, mapOf("available" to false))
                } else {
                    call.respondText(Files.readString(manifestPath), ContentType.Application.Json)
                }
            }

            get("/releases/android/kibot-android-latest.apk") {
                applyDashboardSecurityHeaders(call, cacheControl = "no-store, max-age=0")
                val apkPath = androidReleaseDirectory.resolve("kibot-android-latest.apk")
                if (!Files.exists(apkPath)) {
                    call.respond(HttpStatusCode.NotFound, mapOf("available" to false))
                } else {
                    call.respondFile(apkPath.toFile())
                }
            }

            post("/command") {
                call.respond(HttpStatusCode.Forbidden, mapOf("error" to "dashboard view-only"))
            }
        }
    }

    fun start() {
        if (stateCacheJob?.isActive != true) {
            stateCacheJob = stateCacheScope.launch {
                while (isActive) {
                    runCatching {
                        cachedStateResponse = buildDashboardStateResponse()
                        cachedStateUpdatedAtMs = System.currentTimeMillis()
                    }.onFailure { error ->
                        logger.debug("Dashboard state cache refresh failed: ${error.message}")
                    }
                    delay(500L)
                }
            }
        }
        server.start()
        lanServiceAdvertiser?.let { advertiser ->
            stateCacheScope.launch(Dispatchers.IO) {
                runCatching { advertiser.start() }
                    .onFailure { error ->
                        logger.warn("LAN advertising disabled after startup failure: {}", error.message)
                    }
            }
        }
    }

    fun stop() {
        lanServiceAdvertiser?.stop()
        runCatching { stateCacheJob?.cancel() }
        stateCacheScope.cancel()
        runCatching {
            server.stop(1_000, 2_000)
        }.onFailure { error ->
            logger.warn("Dashboard stop encountered recoverable error: ${error.message}")
        }
    }

    private fun buildDashboardStateResponse(): DashboardStateResponse {
        val state = repository.state.value
        val whatIfJson = readJsonFileOrEmpty(Path.of("state/whatif_results.json"))
        val tradeSummaryJson = readJsonFileOrEmpty(Path.of("state/trade_summary.json"))
        val dailyPnlPct = state.pnlTodayPctLabel.replace("%", "").replace("+", "").toDoubleOrNull() ?: 0.0
        val safeModeActive = state.effectiveState.name == "SAFE_MODE"
        val tradingAllowed = state.liveExecutionEnabled && !safeModeActive
        val dailyLossHardStop = tradingAllowed.not() && dailyPnlPct <= -3.0
        return DashboardStateResponse(
            portfolioValueIdr = state.portfolioValueIdr,
            dailyPnlPct = dailyPnlPct,
            dailyPnlIdr = state.pnlTodayIdr.replace(Regex("[^0-9-]"), "").toDoubleOrNull() ?: 0.0,
            tradingAllowed = tradingAllowed,
            hardStopActive =
                safeModeActive ||
                state.statusMessage.contains("hard stop", ignoreCase = true) ||
                    state.healthSummary.contains("hard stop", ignoreCase = true) ||
                    state.healthSummary.contains("daily_loss_limit", ignoreCase = true) ||
                    dailyLossHardStop,
            botMode = state.operatingMode,
            lastUpdate = java.time.Instant.ofEpochMilli(state.lastUpdatedEpochMs).toString(),
            connections = DashboardConnections(
                KiBot = DashboardConnectionStatus(state.KiBotNodeStatus, 42),
                KiBot = DashboardConnectionStatus(state.KiBotNodeStatus, 150),
            ),
            activePositions = state.holdingsDetailed.map { h ->
                ActivePositionState(h.assetCode, h.currentPriceLabel, h.pnlPctLabel, h.pnlIdrLabel, h.quantityLabel)
            },
            pairScores = state.radarPairs.map { p -> PairScoreState(p) },
            learningState = JsonObject(emptyMap()),
            whatIfSimulation = whatIfJson,
            tradeHistory = tradeSummaryJson,
            rawState = Json.encodeToJsonElement(MacDashboardState.serializer(), state),
        )
    }

    private fun readJsonFileOrEmpty(path: Path): JsonElement {
        val file = path.toFile()
        if (!file.exists() || file.length() == 0L) return JsonObject(emptyMap())
        return runCatching {
            relaxedJson.parseToJsonElement(file.readText())
        }.onFailure { error ->
            logger.warn("Ignoring malformed dashboard JSON file {}: {}", path, error.message)
            runCatching {
                file.parentFile?.mkdirs()
                file.writeText("{}")
            }.onFailure { rewriteError ->
                logger.debug("Failed to self-heal malformed dashboard JSON file {}: {}", path, rewriteError.message)
            }
        }.getOrElse {
            JsonObject(emptyMap())
        }
    }

    private suspend fun handleCommandRequest(request: CommandCenterCommandRequest): CommandCenterCommandReply {
        val command = request.command.trim().lowercase()
        val targetBotId = request.argument
            ?.trim()
            ?.lowercase()
            ?.takeIf { it in setOf("KiBot", "kibot", "KiBot", "main") }
            ?.let(::BotId)
            ?: botId
        val replySnapshotBotId = targetBotId
        val snapshot = repository.state.value.toLiveSnapshot(host, port, replySnapshotBotId)
        return when (command) {
            "/status" -> CommandCenterCommandReply(
                accepted = true,
                message = "Status ${targetBotId.value}: ${snapshot.effectiveState.name} / ${snapshot.syncHealth.name}",
                echoCommand = request.command,
                updatedSnapshot = snapshot,
                issuedAtEpochMs = request.issuedAtEpochMs,
            )
            "/pause_KiBot", "/veto_all" -> {
                commandDispatcher?.dispatch(MacCommand.STOP_BOT, targetBotId)
                CommandCenterCommandReply(
                    accepted = true,
                    message = "Emergency stop requested for ${targetBotId.value}.",
                    echoCommand = request.command,
                    updatedSnapshot = repository.state.value.toLiveSnapshot(host, port, replySnapshotBotId),
                    issuedAtEpochMs = request.issuedAtEpochMs,
                )
            }
            "/sync" -> {
                commandDispatcher?.dispatch(MacCommand.SYNC_NOW, targetBotId)
                CommandCenterCommandReply(
                    accepted = true,
                    message = "Sync requested for ${targetBotId.value}.",
                    echoCommand = request.command,
                    updatedSnapshot = repository.state.value.toLiveSnapshot(host, port, replySnapshotBotId),
                    issuedAtEpochMs = request.issuedAtEpochMs,
                )
            }
            "/start" -> {
                commandDispatcher?.dispatch(MacCommand.START_BOT, targetBotId)
                CommandCenterCommandReply(
                    accepted = true,
                    message = "Start requested for ${targetBotId.value}.",
                    echoCommand = request.command,
                    updatedSnapshot = repository.state.value.toLiveSnapshot(host, port, replySnapshotBotId),
                    issuedAtEpochMs = request.issuedAtEpochMs,
                )
            }
            "/stop" -> {
                commandDispatcher?.dispatch(MacCommand.STOP_BOT, targetBotId)
                CommandCenterCommandReply(
                    accepted = true,
                    message = "Stop requested for ${targetBotId.value}.",
                    echoCommand = request.command,
                    updatedSnapshot = repository.state.value.toLiveSnapshot(host, port, replySnapshotBotId),
                    issuedAtEpochMs = request.issuedAtEpochMs,
                )
            }
            else -> CommandCenterCommandReply(
                accepted = false,
                message = "Command not supported on server: ${request.command}",
                echoCommand = request.command,
                issuedAtEpochMs = request.issuedAtEpochMs,
            )
        }
    }
}

private data class DashboardCommandAuth(
    val required: Boolean,
    val token: String,
    val allowedCidrs: List<IpCidr> = emptyList(),
) {
    fun allowSession(call: io.ktor.server.application.ApplicationCall): Boolean {
        if (!required) return true
        if (token.isBlank()) return false
        if (allowedCidrs.isNotEmpty()) {
            val clientIp = extractClientIp(call) ?: return false
            if (allowedCidrs.none { it.contains(clientIp) }) return false
        }
        return extractToken(call) == token
    }

    private fun extractToken(call: io.ktor.server.application.ApplicationCall): String? {
        val headerValue = call.request.header("Authorization")?.trim().orEmpty()
        if (headerValue.startsWith("Bearer ", ignoreCase = true)) {
            return headerValue.removePrefix("Bearer ").trim().takeIf { it.isNotBlank() }
        }
        return call.request.queryParameters["token"]?.trim()?.takeIf { it.isNotBlank() }
    }

    private fun extractClientIp(call: io.ktor.server.application.ApplicationCall): java.net.InetAddress? {
        val forwarded = call.request.header("X-Forwarded-For")
            ?.split(",")
            ?.firstOrNull()
            ?.trim()
            ?.takeIf { it.isNotBlank() }
        val raw = forwarded ?: call.request.local.remoteHost
        return runCatching { java.net.InetAddress.getByName(raw) }.getOrNull()
    }

    companion object {
        fun fromEnv(bindHost: String): DashboardCommandAuth {
            val token = (System.getenv("KIBOT_DASHBOARD_AUTH_TOKEN") ?: System.getenv("KICRYP_DASHBOARD_AUTH_TOKEN"))?.trim().orEmpty()
            val required = token.isNotBlank() && !isLoopbackHost(bindHost)
            val allowlist = System.getenv("KIBOT_DASHBOARD_ALLOWED_IPS")
                ?: System.getenv("KIBOT_DASHBOARD_ALLOWED_CIDRS")
                ?: System.getenv("KICRYP_DASHBOARD_ALLOWED_IPS")
                ?: System.getenv("KICRYP_DASHBOARD_ALLOWED_CIDRS")
            val allowedCidrs = allowlist
                ?.split(",", " ", "\n", "\t")
                ?.mapNotNull { raw -> raw.trim().takeIf { it.isNotBlank() }?.let(IpCidr::parseOrNull) }
                .orEmpty()
            return DashboardCommandAuth(
                required = required,
                token = token,
                allowedCidrs = allowedCidrs,
            )
        }

        private fun isLoopbackHost(host: String): Boolean {
            val normalized = host.trim().lowercase()
            return normalized in setOf("127.0.0.1", "localhost", "::1")
        }
    }
}

private data class IpCidr(
    val network: java.net.InetAddress,
    val prefixBits: Int,
) {
    fun contains(address: java.net.InetAddress): Boolean {
        val a = address.address
        val n = network.address
        if (a.size != n.size) return false
        val fullBytes = prefixBits / 8
        val remainingBits = prefixBits % 8
        for (idx in 0 until fullBytes) {
            if (a[idx] != n[idx]) return false
        }
        if (remainingBits == 0) return true
        val mask = (0xFF shl (8 - remainingBits)) and 0xFF
        return (a[fullBytes].toInt() and mask) == (n[fullBytes].toInt() and mask)
    }

    companion object {
        fun parseOrNull(raw: String): IpCidr? {
            val token = raw.trim()
            if (token.isBlank()) return null
            val parts = token.split("/", limit = 2)
            val addr = runCatching { java.net.InetAddress.getByName(parts[0].trim()) }.getOrNull() ?: return null
            val maxBits = addr.address.size * 8
            val prefix = parts.getOrNull(1)
                ?.trim()
                ?.toIntOrNull()
                ?.coerceIn(0, maxBits)
                ?: maxBits
            return IpCidr(network = masked(addr, prefix), prefixBits = prefix)
        }

        private fun masked(address: java.net.InetAddress, prefixBits: Int): java.net.InetAddress {
            val bytes = address.address.clone()
            val fullBytes = prefixBits / 8
            val remainingBits = prefixBits % 8
            for (idx in fullBytes until bytes.size) {
                bytes[idx] = 0
            }
            if (remainingBits != 0 && fullBytes < bytes.size) {
                val mask = (0xFF shl (8 - remainingBits)) and 0xFF
                bytes[fullBytes] = (bytes[fullBytes].toInt() and mask).toByte()
            }
            return java.net.InetAddress.getByAddress(bytes)
        }
    }
}

private class DashboardCommandRateLimiter(
    private val maxCommandsPerMinute: Int = (System.getenv("KIBOT_DASHBOARD_COMMANDS_PER_MIN") 
        ?: System.getenv("KICRYP_DASHBOARD_COMMANDS_PER_MIN"))?.toIntOrNull() ?: 30
        .coerceIn(5, 600),
) {
    private var windowStartMs: Long = System.currentTimeMillis()
    private var count: Int = 0

    fun allow(nowMs: Long = System.currentTimeMillis()): Boolean {
        if (nowMs - windowStartMs >= 60_000L) {
            windowStartMs = nowMs
            count = 0
        }
        count++
        return count <= maxCommandsPerMinute
    }
}

private fun MacDashboardState.toLiveSnapshot(serverHost: String, serverPort: Int): CommandCenterLiveSnapshot {
    return toLiveSnapshot(serverHost, serverPort, BotId("main"))
}

private fun MacDashboardState.toLiveSnapshot(
    serverHost: String,
    serverPort: Int,
    botId: BotId,
): CommandCenterLiveSnapshot {
    val serverId = "$serverHost:$serverPort"
        return CommandCenterLiveSnapshot(
        serverId = serverId,
        serverLabel = serverLocation.ifBlank { serverId },
        botId = botId,
        effectiveState = effectiveState,
        syncHealth = runCatching { com.kibot.shared.models.SyncHealth.valueOf(syncHealth) }.getOrDefault(com.kibot.shared.models.SyncHealth.DEGRADED),
        liveExecutionEnabled = liveExecutionEnabled,
        operatingMode = runCatching { com.kibot.shared.models.BotMode.valueOf(operatingMode) }.getOrDefault(com.kibot.shared.models.BotMode.GROWTH),
        edgeConfidence = runCatching { com.kibot.shared.models.EdgeConfidence.valueOf(edgeConfidence) }.getOrDefault(com.kibot.shared.models.EdgeConfidence.MEDIUM),
        marketRegime = runCatching { com.kibot.shared.models.MarketRegime.valueOf(marketRegime) }.getOrDefault(com.kibot.shared.models.MarketRegime.HIGH_VOLATILITY_UNCLEAR),
        aiProviderSummary = aiProviderSummary,
        upstreamMarker = upstreamMarker,
        activeEngine = activeEngine,
        standbyEngine = standbyEngine,
        topCandidate = topCandidate,
        scanUniverseCount = scanUniverseCount,
        leaseTerm = leaseTerm,
        healthSummary = healthSummary,
        lastRejectedReason = lastRejectedReason,
        statusMessage = statusMessage,
        lastHeartbeatLabel = lastHeartbeatLabel,
        lastUpdatedLabel = lastUpdatedLabel,
        totalValueIdr = totalValueIdr,
        portfolioValueIdr = portfolioValueIdr,
        freeIdrLabel = freeIdrLabel,
        referenceQuoteAssetPriceIdr = referenceQuoteAssetPriceIdr,
        pnlTodayIdr = pnlTodayIdr,
        pnlTodayPctLabel = pnlTodayPctLabel,
        totalReturnIdr = pnlTodayIdr,
        totalReturnPctLabel = pnlTodayPctLabel,
        cumulativeReturnPctLabel = cumulativeReturnPctLabel,
        return7dIdr = return7dIdr,
        return7dPctLabel = return7dPctLabel,
        return30dIdr = return30dIdr,
        return30dPctLabel = return30dPctLabel,
        exchangePingMs = exchangePingMs,
        exchangePingValueMs = exchangePingValueMs,
        KiBotPingMs = null,
        KiBotNodeStatus = KiBotNodeStatus,
        kibotNodeStatus = kibotNodeStatus,
        KiBotNodeStatus = KiBotNodeStatus,
        serverUptime = serverUptime,
        releaseLabel = releaseLabel,
        targetPursuitLabel = targetPursuitLabel,
        radarPairs = radarPairs,
        holdingsDetailed = holdingsDetailed.map {
            CommandCenterHolding(
                assetCode = it.assetCode,
                assetLabel = it.assetLabel,
                quantityLabel = it.quantityLabel,
                valueIdrLabel = it.valueIdrLabel,
                entryPriceLabel = it.entryPriceLabel,
                currentPriceLabel = it.currentPriceLabel,
                pnlIdrLabel = it.pnlIdrLabel,
                pnlPctLabel = it.pnlPctLabel,
            )
        },
        recentOrders = recentOrders.map {
            CommandCenterOrder(
                timestampEpochMs = it.timestampEpochMs,
                pair = it.pair,
                side = it.side,
                status = it.status,
                orderType = it.orderType,
                detail = it.detail,
                entryPriceLabel = it.entryPriceLabel,
                exitPriceLabel = it.exitPriceLabel,
                outcomeLabel = it.outcomeLabel,
                pnlIdrLabel = it.pnlIdrLabel,
                pnlPctLabel = it.pnlPctLabel,
            )
        },
        liveTimeline = liveTimeline.map {
            CommandCenterTimelineEntry(it.timestampEpochMs, it.category, it.message)
        },
        netWorthHistory = netWorthHistory.map {
            com.kibot.shared.models.CommandCenterNetWorthPoint(
                timestamp = it.timestampEpochMs,
                value = it.valueIdrLabel,
            )
        },
        assetAllocationDetailed = assetAllocationDetailed.map {
            com.kibot.shared.models.CommandCenterAssetAllocation(
                coin = it.coin,
                percentageLabel = it.percentageLabel,
                valueLabel = it.valueIdrLabel,
            )
        },
        whatIfSimulation = whatIfSimulation,
        updatedAtEpochMs = lastUpdatedEpochMs,
    )
}

private fun applyDashboardSecurityHeaders(
    call: io.ktor.server.application.ApplicationCall,
    cacheControl: String = "no-store, no-cache, must-revalidate, max-age=0",
) {
    call.response.header("Cache-Control", cacheControl)
    call.response.header("Pragma", "no-cache")
    call.response.header("Expires", "0")
    call.response.header("X-Content-Type-Options", "nosniff")
    call.response.header("X-Frame-Options", "DENY")
    call.response.header("Referrer-Policy", "no-referrer")
    call.response.header(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none';",
    )
}

private fun FlowContent.metricCard(label: String, value: String, caption: String, valueId: String, captionId: String) {
    div("metric-card ${metricCardClass(value, caption)}") {
        attributes["id"] = "${valueId}-card"
        span("metric-label") { +label }
        span("metric-value") {
            attributes["id"] = valueId
            +value
        }
        span("metric-caption") {
            attributes["id"] = captionId
            +caption
        }
    }
}

private fun dashboardStatusLabel(state: MacDashboardState): String = when {
    state.effectiveState.name == "SAFE_MODE" -> "SAFE"
    state.syncHealth.equals("BROKEN", ignoreCase = true) -> "LAG"
    state.effectiveState.name == "DEGRADED" || state.syncHealth.equals("DEGRADED", ignoreCase = true) -> "WARM"
    state.effectiveState.name == "STOPPED" -> "OFF"
    else -> "LIVE"
}

private fun dashboardStatusClass(state: MacDashboardState): String = when (dashboardStatusLabel(state)) {
    "SAFE" -> "pill-safe"
    "LAG" -> "pill-lag"
    "WARM" -> "pill-warm"
    "OFF" -> "pill-off"
    else -> "pill-live"
}

private fun metricCardClass(value: String, caption: String): String =
    if (isNegativeTone(value, caption)) "metric-card-loss" else "metric-card-gain"

private fun filledRadarPairs(pairs: List<String>): List<String> {
    val fallback = listOf(
        "xrp_idr",
        "doge_idr",
        "trx_idr",
        "pepe_idr",
        "shib_idr",
        "fartcoin_idr",
        "jellyjelly_idr",
        "sol_idr",
        "btc_idr",
        "arb_idr",
        "plpa_idr",
    )
    return (pairs.map { it.lowercase() } + fallback)
        .filter { it.isNotBlank() && it != "--" }
        .distinct()
        .take(9)
}

private fun radarPillClass(pair: String): String {
    val token = pair.lowercase()
    return when {
        token.contains("xrp") || token.contains("btc") || token.contains("eth") -> "radar-pill-blue"
        token.contains("doge") || token.contains("trx") -> "radar-pill-warm"
        token.contains("pepe") || token.contains("fart") || token.contains("shib") -> "radar-pill-mint"
        token.contains("jelly") || token.contains("plpa") || token.contains("arb") -> "radar-pill-purple"
        else -> "radar-pill-slate"
    }
}

private fun pingPillClass(pingText: String): String {
    val digits = pingText.filter { it.isDigit() }
    val ping = digits.toIntOrNull() ?: return "pill-neutral"
    return when {
        ping <= 90 -> "pill-live"
        ping <= 220 -> "pill-warm"
        else -> "pill-lag"
    }
}

private fun pairHeatLabel(pingText: String): String {
    val digits = pingText.filter { it.isDigit() }
    val ping = digits.toIntOrNull() ?: return "LIVE"
    return when {
        ping <= 90 -> "LIVE"
        ping <= 220 -> "WARM"
        else -> "LAG"
    }
}

private fun isNegativeTone(value: String, caption: String): Boolean =
    value.trim().startsWith("-") || caption.trim().startsWith("-")

private fun compactAiStatusLabel(summary: String): String {
    val normalized = summary.lowercase()
    val healthy = "sehat:" in normalized || "healthy:" in normalized
    val limited = "limited" in normalized
    val skipped = "skip:" in normalized || "forbidden" in normalized || "failure" in normalized
    return when {
        healthy && !limited && !skipped -> "AI ONLINE"
        healthy -> "AI LIMITED"
        skipped -> "AI SKIP"
        else -> "AI OFFLINE"
    }
}

private fun aiPillClass(summary: String): String = when (compactAiStatusLabel(summary)) {
    "AI ONLINE" -> "pill-live"
    "AI LIMITED" -> "pill-warm"
    "AI SKIP" -> "pill-lag"
    else -> "pill-neutral"
}

private fun targetPillClass(label: String): String = when (label.uppercase()) {
    "OVERDRIVE" -> "pill-safe"
    "FULL_CHASE" -> "pill-lag"
    "CHASE" -> "pill-live"
    "LOCK_PROFIT" -> "pill-blue"
    else -> "pill-neutral"
}

private const val WEB_LOG_FRESHNESS_WINDOW_MS = 2 * 60 * 60 * 1000L

private fun dashboardStyles(): String = """
    :root {
      --bg-deep: #05080f;
      --bg-card: rgba(16, 24, 45, 0.65);
      --bg-glass: rgba(255, 255, 255, 0.03);
      --border: rgba(255, 255, 255, 0.08);
      --text-main: #f0f4ff;
      --text-dim: #94a3b8;
      --accent-blue: #38bdf8;
      --accent-green: #22c55e;
      --accent-red: #ef4444;
      --accent-yellow: #fbbf24;
      --accent-purple: #a855f7;
      --shadow-lg: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
      --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    * { box-sizing: border-box; margin: 0; padding: 0; }
    
    body {
      background: var(--bg-deep);
      color: var(--text-main);
      font-family: 'Inter', -apple-system, system-ui, sans-serif;
      min-height: 100vh;
      line-height: 1.5;
      overflow-x: hidden;
      background-image: 
        radial-gradient(circle at 0% 0%, rgba(56, 189, 248, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 100% 100%, rgba(168, 85, 247, 0.08) 0%, transparent 40%);
    }

    .v5-container {
      max-width: 1700px;
      margin: 0 auto;
      padding: 20px;
      display: grid;
      grid-template-areas:
        "nav nav nav"
        "col1 col2 col3";
      grid-template-columns: 1fr 1fr 0.8fr;
      gap: 20px;
    }

    @media (max-width: 1300px) {
      .v5-container {
        grid-template-areas:
          "nav nav"
          "col1 col2"
          "col3 col3";
        grid-template-columns: 1fr 1fr;
      }
    }

    @media (max-width: 900px) {
      .v5-container {
        grid-template-areas: "nav" "col1" "col2" "col3";
        grid-template-columns: 1fr;
      }
    }

    .nav-bar {
      grid-area: nav;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      padding: 15px 25px;
      border-radius: 20px;
      border: 1px solid var(--border);
      box-shadow: var(--shadow-lg);
    }

    .nav-brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .nav-brand h1 {
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.02em;
      background: linear-gradient(90deg, #fff, #94a3b8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .system-pnl {
      text-align: right;
    }

    .system-pnl .total { font-size: 20px; font-weight: 700; color: #fff; }
    .system-pnl .daily { font-size: 14px; font-weight: 600; }

    .card-v5 {
      background: var(--bg-card);
      border-radius: 24px;
      border: 1px solid var(--border);
      padding: 24px;
      position: relative;
      overflow: hidden;
      box-shadow: var(--shadow-lg);
    }

    .card-v5::before {
      content: "";
      position: absolute;
      top: 0; left: 0; right: 0; height: 1px;
      background: linear-gradient(90deg, transparent, var(--border), transparent);
    }

    .card-title {
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--text-dim);
      margin-bottom: 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    /* Active Positions Table */
    .pos-table { width: 100%; border-collapse: collapse; }
    .pos-table th { text-align: left; padding: 12px 8px; font-size: 12px; color: var(--text-dim); border-bottom: 1px solid var(--border); }
    .pos-table td { padding: 16px 8px; border-bottom: 1px dotted rgba(255,255,255,0.05); }

    .token-badge {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .token-icon {
      width: 32px; height: 32px;
      border-radius: 10px;
      background: var(--bg-glass);
      display: flex; align-items: center; justify-content: center;
      font-weight: 800; font-size: 11px;
      border: 1px solid var(--border);
    }

    .pnl-chip {
      padding: 4px 10px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 700;
    }
    .pnl-gain { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.2); }
    .pnl-loss { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.2); }

    /* Simulation Widget */
    .sim-item {
      background: var(--bg-glass);
      border-radius: 16px;
      padding: 16px;
      margin-bottom: 12px;
      border: 1px solid transparent;
      transition: var(--transition);
    }
    .sim-item:hover { border-color: rgba(56, 189, 248, 0.3); transform: translateX(5px); }
    .sim-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
    .sim-pair { font-weight: 700; font-size: 15px; }
    .sim-ev { font-family: monospace; color: var(--accent-blue); font-weight: 700; }
    .sim-bar-bg { width: 100%; height: 6px; background: rgba(255,255,255,0.05); border-radius: 3px; overflow: hidden; }
    .sim-bar-fill { height: 100%; background: var(--accent-blue); }

    /* Manager Logs */
    .log-container {
      max-height: 400px;
      overflow-y: auto;
      font-size: 14px;
    }
    .log-row {
      padding: 10px 0;
      border-left: 2px solid var(--border);
      padding-left: 15px;
      margin-bottom: 5px;
      position: relative;
    }
    .log-row::after {
      content: "";
      position: absolute;
      left: -5px; top: 15px;
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--text-dim);
    }
    .log-time { font-size: 11px; color: var(--text-dim); margin-bottom: 2px; }

    /* Connectivity Status */
    .net-pulse {
      width: 10px; height: 10px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 8px;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.7); }
      70% { transform: scale(1.1); box-shadow: 0 0 0 10px rgba(74, 222, 128, 0); }
      100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
    }

    .status-up { background: var(--accent-green); }
    .status-warn { background: var(--accent-yellow); }
    .status-down { background: var(--accent-red); }

    .health-section { margin-top: 25px; }
    .health-row {
      display: flex; justify-content: space-between; align-items: center;
      padding: 12px; background: var(--bg-glass); border-radius: 12px; margin-bottom: 8px;
    }

    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
      margin: 0;
      font-size: 15px;
      line-height: 1.45;
      color: #dbe7ff;
    }
    .ping-badge-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 6px 0 10px;
    }
    .target-ring-shell {
      display: grid;
      gap: 12px;
      justify-items: center;
      align-content: center;
      min-height: 160px;
      padding-top: 10px;
    }
    .target-ring {
      width: 170px;
      height: 170px;
      border-radius: 50%;
      background: conic-gradient(#32d583 0 25%, rgba(255,255,255,0.11) 25% 100%);
      display: grid;
      place-items: center;
      animation: ringGlow 2.4s ease-in-out infinite;
    }
    .target-ring-core {
      width: 108px;
      height: 108px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: linear-gradient(180deg, #141f3f, #0e1730);
      border: 1px solid rgba(255,255,255,0.08);
      text-align: center;
    }
    .target-ring-core span {
      color: #9db2da;
      font-size: 13px;
      font-weight: 700;
      line-height: 1;
    }
    .target-ring-core strong {
      color: #f2f8ff;
      font-size: 28px;
      font-weight: 900;
      line-height: 1;
    }
    @keyframes ringGlow {
      0%, 100% { filter: saturate(1); box-shadow: 0 0 0 rgba(50,213,131,0); }
      50% { filter: saturate(1.1); box-shadow: 0 0 26px rgba(50,213,131,0.18); }
    }
    .hero-pnl-gain { color: #2dd881; }
    .hero-pnl-loss { color: #ff6b7a; }
    .hero-clock { min-width: 0; }
    .hero-card .pair-support-copy {
      margin-top: 10px;
      max-width: 95%;
      color: #9fbaea;
      font-size: 14px;
    }
    .returns-grid {
      display: grid;
      gap: 12px;
    }
    .portfolio-card { display: grid; gap: 4px; align-content: start; padding: 10px 12px; }
    .portfolio-update {
      margin: 0;
      color: #dbe7ff;
      font-size: 14px;
      font-weight: 700;
    }
    .returns-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .metric-card {
      padding: 8px 10px;
      display: grid;
      gap: 2px;
      background: rgba(255,255,255,0.035);
      border: 1px solid rgba(255,255,255,0.06);
      min-height: 74px;
      border-radius: 22px;
    }
    .metric-card-gain .metric-value,
    .metric-card-gain .metric-caption { color: #2dd881; }
    .metric-card-loss .metric-value,
    .metric-card-loss .metric-caption { color: #ff6b7a; }
    .metric-label {
      color: #dbe7ff;
      font-size: 14px;
      font-weight: 700;
    }
    .metric-value {
      font-size: 20px;
      font-weight: 800;
    }
    .metric-caption {
      font-size: 15px;
      font-weight: 700;
    }
    .card { padding: 16px; min-height: 0; background: linear-gradient(135deg, rgba(24,34,66,0.96), rgba(17,27,49,0.92)); }
    .live-pair-card { min-height: 0; }
    .activity-card { min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; padding: 18px; }
    .logs-card { height: 100%; align-self: stretch; }
    .trade-card { height: 100%; }
    .card-header-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
    }
    .card h2 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
    }
    .pair-focus-shell {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 12px;
      align-items: center;
      margin: 4px 0 10px;
      padding: 4px 2px 0;
    }
    .pair-avatar {
      width: 50px;
      height: 50px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(180deg, rgba(88,146,255,0.32), rgba(88,146,255,0.16));
      color: #84b8ff;
      font-size: 19px;
      font-weight: 900;
      border: 1px solid rgba(132,184,255,0.18);
      flex-shrink: 0;
    }
    .pair-focus-copy { min-width: 0; }
    .pair-hero {
      font-size: clamp(20px, 2vw, 32px);
      font-weight: 900;
      line-height: 1;
      letter-spacing: -0.04em;
      margin-bottom: 0;
    }
    .muted-copy {
      margin: 0;
      color: var(--muted);
      line-height: 1.35;
      font-size: 13px;
    }
    .radar-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 2px;
    }
    .radar-pill {
      min-height: 50px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 8px 10px;
      border-radius: 16px;
      background: rgba(124, 92, 255, 0.16);
      border: 1px solid rgba(167, 139, 250, 0.18);
      color: #b799ff;
      font-size: 14px;
      font-weight: 800;
      letter-spacing: 0.01em;
    }
    .radar-pill-blue { background: rgba(96,165,250,0.16); color: #84b8ff; border-color: rgba(96,165,250,0.2); }
    .radar-pill-warm { background: rgba(250,204,21,0.12); color: #ffd85a; border-color: rgba(250,204,21,0.18); }
    .radar-pill-mint { background: rgba(45,216,129,0.12); color: #63e8aa; border-color: rgba(45,216,129,0.18); }
    .radar-pill-purple { background: rgba(183,153,255,0.16); color: #c3a8ff; border-color: rgba(183,153,255,0.18); }
    .radar-pill-slate { background: rgba(255,255,255,0.06); color: #dbe7ff; border-color: rgba(255,255,255,0.1); }
    .radar-pill-empty {
      color: transparent;
      background: rgba(255,255,255,0.035);
      border-color: rgba(255,255,255,0.04);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.02);
    }
    .allocation-shell {
      display: grid;
      grid-template-columns: 220px 1fr;
      gap: 16px;
      align-items: center;
      min-height: 0;
    }
    .allocation-chart-wrap {
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .allocation-chart {
      width: 180px;
      height: 180px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      position: relative;
      background: rgba(255,255,255,0.05);
    }
    .allocation-chart::after {
      content: "";
      width: 96px;
      height: 96px;
      border-radius: 50%;
      background: linear-gradient(180deg, #151f40, #10182b);
      border: 1px solid rgba(255,255,255,0.08);
      position: absolute;
    }
    .allocation-center {
      position: relative;
      z-index: 1;
      display: grid;
      gap: 4px;
      text-align: center;
    }
    .allocation-center span {
      color: #dbe7ff;
      font-size: 16px;
      font-weight: 800;
    }
    .allocation-center strong {
      color: #ffffff;
      font-size: 30px;
      line-height: 1;
    }
    .allocation-legend {
      display: grid;
      gap: 12px;
      align-content: start;
      max-height: 260px;
      overflow-y: auto;
      padding-right: 4px;
    }
    .allocation-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 14px;
      border-radius: 18px;
      background: rgba(255,255,255,0.045);
      border: 1px solid rgba(255,255,255,0.06);
    }
    .allocation-row-left {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .allocation-dot {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .allocation-code {
      font-size: 22px;
      font-weight: 800;
    }
    .allocation-pct {
      font-size: 28px;
      font-weight: 900;
    }
    .log-list {
      display: grid;
      min-height: 0;
      height: 100%;
      gap: 8px;
      align-content: start;
      overflow-y: auto;
      overscroll-behavior: contain;
      -webkit-overflow-scrolling: touch;
      padding-right: 4px;
    }
    .timeline-row {
      padding: 14px;
      border-radius: 20px;
      background: rgba(255,255,255,0.045);
      border: 1px solid rgba(255,255,255,0.06);
      line-height: 1.45;
      display: grid;
      gap: 6px;
    }
    .timeline-head,
    .trade-row-shell {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 14px;
      align-items: start;
    }
    .timeline-head { grid-template-columns: auto 1fr; }
    .timeline-badge,
    .trade-side,
    .trade-status {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 94px;
      padding: 10px 14px;
      border-radius: 16px;
      font-size: 14px;
      font-weight: 900;
      letter-spacing: 0.03em;
    }
    .timeline-badge-status { color: #95b6ff; background: rgba(96,165,250,0.14); }
    .timeline-badge-rotasi { color: #ffd85a; background: rgba(250,204,21,0.14); }
    .timeline-badge-target { color: #c3a8ff; background: rgba(183,153,255,0.14); }
    .timeline-badge-hold { color: #84b8ff; background: rgba(96,165,250,0.14); }
    .timeline-badge-health { color: #63e8aa; background: rgba(45,216,129,0.14); }
    .timeline-badge-log { color: #dbe7ff; background: rgba(255,255,255,0.08); }
    .timeline-time,
    .trade-time {
      color: #dbe7ff;
      font-size: 15px;
      font-weight: 700;
      align-self: center;
    }
    .timeline-copy {
      color: var(--text);
      font-size: 18px;
    }
    .trade-side-buy { color: #2dd881; background: rgba(45,216,129,0.14); }
    .trade-side-sell { color: #ff9b7a; background: rgba(255,107,122,0.12); }
    .trade-side-hold { color: #95b6ff; background: rgba(96,165,250,0.12); }
    .trade-main {
      display: grid;
      gap: 6px;
      min-width: 0;
    }
    .trade-pair {
      font-size: 24px;
      font-weight: 900;
      line-height: 1;
    }
    .trade-detail {
      color: #dbe7ff;
      font-size: 18px;
    }
    .trade-status {
      color: #63e8aa;
      background: rgba(45,216,129,0.12);
    }
    .empty-state {
      min-height: 100%;
      display: grid;
      align-content: center;
      gap: 8px;
      padding: 18px;
      border-radius: 20px;
      background: rgba(255,255,255,0.035);
      border: 1px solid rgba(255,255,255,0.05);
      text-align: left;
    }
    .empty-title {
      color: #dbe7ff;
      font-size: 18px;
      font-weight: 800;
    }
    .empty-copy {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }
    .log-list {
      font-family: "SF Pro Text", "Segoe UI", sans-serif;
      color: var(--muted);
      font-size: 12px;
    }
    @media (max-width: 920px) {
      .v2-shell {
        grid-template-columns: 1fr;
        grid-template-areas:
          "header"
          "switcher"
          "overview"
          "KiBot"
          "KiBot"
          "ticker";
      }
      .v2-switcher {
        grid-template-columns: 1fr;
      }
      .v2-overview {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .v2-ticker {
        grid-template-columns: 1fr;
      }
      .page-shell,
      .bento-shell,
      .column,
      .returns-grid,
      .allocation-shell {
        grid-template-columns: 1fr;
      }
      .bento-shell {
        grid-template-areas:
          "master"
          "target"
          "heartbeat"
          "KiBot"
          "KiBot"
          "livepairs";
        grid-template-rows: auto;
      }
      .column-left,
      .column-right {
        grid-template-rows: auto;
      }
      .hero-topbar {
        flex-direction: column;
      }
      .hero-topbar-right {
        align-items: flex-start;
      }
      .pair-focus-shell,
      .trade-row-shell {
        grid-template-columns: 1fr;
      }
      .allocation-chart {
        width: 210px;
        height: 210px;
      }
      .page-shell {
        height: auto;
        min-height: 100vh;
        padding: 18px 14px 28px;
        overflow-y: auto;
      }
      .hero-chip-strip {
        flex-wrap: wrap;
      }
      .radar-pill {
        min-height: 58px;
        font-size: 16px;
      }
      body { overflow: auto; }
    }
    @media (max-width: 1360px) {
      .page-shell {
        width: min(100%, 1380px);
        grid-template-columns: minmax(0, 1.08fr) minmax(340px, 0.92fr);
      }
      .hero-card {
        min-height: 248px;
      }
      .hero-balance {
        font-size: clamp(38px, 4.8vw, 62px);
      }
      .allocation-shell {
        grid-template-columns: 190px 1fr;
      }
      .allocation-chart {
        width: 160px;
        height: 160px;
      }
      .allocation-chart::after {
        width: 88px;
        height: 88px;
      }
      .allocation-code {
        font-size: 20px;
      }
      .allocation-pct {
        font-size: 24px;
      }
    }
    @media (max-width: 1180px) {
      .page-shell,
      .bento-shell {
        grid-template-columns: 1fr;
        min-height: auto;
      }
      .column-left,
      .column-right {
        grid-template-rows: auto;
      }
      .hero-chip-strip {
        flex-wrap: wrap;
      }
      .activity-card,
      .trade-card,
      .logs-card {
        min-height: 340px;
      }
    }
""".trimIndent()

private fun detectLanProbeUrl(host: String, port: Int): String? {
    if (host != "0.0.0.0") {
        return "http://$host:$port/api/lan/ping"
    }
    val lanAddress = runCatching {
        Collections.list(NetworkInterface.getNetworkInterfaces())
            .asSequence()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { Collections.list(it.inetAddresses).asSequence() }
            .firstOrNull { address -> !address.isLoopbackAddress && address.hostAddress?.contains(':') == false }
            ?.hostAddress
    }.getOrNull()
    return lanAddress?.let { "http://$it:$port/api/lan/ping" }
}

private fun isBenignClientDisconnect(error: Throwable): Boolean {
    return generateSequence(error) { it.cause }.any { cause ->
        cause is CancellationException ||
            cause is EOFException ||
            cause is ClosedChannelException ||
            (cause is IOException && (
                cause.message?.contains("Broken pipe", ignoreCase = true) == true ||
                    cause.message?.contains("Connection reset", ignoreCase = true) == true ||
                    cause.message?.contains("Channel was closed", ignoreCase = true) == true
                ))
    }
}

private fun locateDashboardIcon(): File? {
    val cwd = File(System.getProperty("user.dir"))
    val candidates = listOf(
        File("/home/ubuntu/KiCryp/kibot-small.png"),
        File("/home/ubuntu/KiCryp/kibot.png"),
        File(cwd, "kibot-small.png"),
        File(cwd, "kibot.png"),
        File(cwd, "../../kibot-small.png"),
        File(cwd, "../../kibot.png"),
        File(cwd, "../kibot-small.png"),
        File(cwd, "../kibot.png"),
    )
    return candidates.firstOrNull { it.exists() }
}

@Serializable
private data class LanPingResponse(
    val ok: Boolean,
    val host: String,
    val port: Int,
    val lanProbeUrl: String?,
)
