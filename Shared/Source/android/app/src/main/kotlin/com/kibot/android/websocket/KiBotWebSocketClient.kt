package com.kibot.android.websocket

import android.net.Uri
import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.kibot.android.data.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.util.concurrent.TimeUnit
import kotlin.math.min

class KiBotWebSocketClient(
    private var wsUrl: String = ServerConfig().getUrl()
) {
    private var webSocket: WebSocket? = null
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS)
        .build()
    
    private val gson = Gson()
    private var reconnectJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    // State flows for UI
    private val _connectionStatus = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    val connectionStatus: StateFlow<ConnectionStatus> = _connectionStatus
    
    private val _botState = MutableStateFlow(BotState())
    val botState: StateFlow<BotState> = _botState
    
    private val _trades = MutableSharedFlow<TradeData>(replay = 50)
    val trades: SharedFlow<TradeData> = _trades
    
    private val _errors = MutableSharedFlow<String>()
    val errors: SharedFlow<String> = _errors
    private val pendingDesiredStates = mutableMapOf<String, Boolean>()
    private var connectionTargets: List<String> = buildConnectionTargets(wsUrl)
    private var activeTargetIndex = 0

    private var lastPingTime = 0L
    private var isConnecting = false
    private var reconnectAttempt = 0
    private var lastMessageAtMs = 0L
    private var watchdogJob: Job? = null
    private var lastFullStateRequestAtMs = 0L

    fun connect() {
        if (isConnecting || _connectionStatus.value == ConnectionStatus.CONNECTED) {
            Log.i(TAG, "⚠️ Already connected or connecting, skipping")
            return
        }
        reconnectJob?.cancel()
        reconnectJob = null
        webSocket?.cancel()
        webSocket = null

        isConnecting = true
        _connectionStatus.value = ConnectionStatus.CONNECTING
        wsUrl = connectionTargets.getOrElse(activeTargetIndex) { wsUrl }
        Log.i(TAG, "🔌 Initiating WebSocket connection to: $wsUrl")
        
        scope.launch {
            try {
                val request = Request.Builder()
                    .url(wsUrl)
                    .build()
                Log.i(TAG, "📤 Creating WebSocket with URL: $wsUrl")
                webSocket = client.newWebSocket(request, KiBotWebSocketListener())
                Log.i(TAG, "📤 WebSocket request sent")
            } catch (e: Exception) {
                Log.e(TAG, "🚨 Connection error: ${e.message}", e)
                _errors.emit("Connection failed: ${e.message}")
                _connectionStatus.value = ConnectionStatus.ERROR
                isConnecting = false
                scheduleReconnect()
            }
        }
    }

    fun disconnect() {
        Log.d(TAG, "Disconnecting")
        reconnectJob?.cancel()
        watchdogJob?.cancel()
        webSocket?.close(1000, "User requested disconnect")
        webSocket = null
        isConnecting = false
        _connectionStatus.value = ConnectionStatus.DISCONNECTED
        scope.coroutineContext.cancelChildren()
    }

    fun reconnect(url: String) {
        val normalized = url.trim()
        if (normalized.isBlank()) return
        val shouldReconnect = normalized != wsUrl || _connectionStatus.value != ConnectionStatus.CONNECTED
        wsUrl = normalized
        connectionTargets = buildConnectionTargets(normalized)
        activeTargetIndex = 0
        if (!shouldReconnect) return
        disconnect()
        connect()
    }

    fun subscribe() {
        val message = SubscribeMessage(
            channels = listOf("state", "trades", "heartbeat")
        )
        sendMessage(gson.toJson(message))
    }

    fun toggleBot(botName: String, enable: Boolean) {
        try {
            val normalizedBotName = botName.trim().lowercase()
            val commandName = if (enable) "/start" else "/stop"
            
            val command = mapOf(
                "command" to commandName,
                "argument" to normalizedBotName,
                "idempotencyKey" to "android_${System.currentTimeMillis()}",
                "issuedAtEpochMs" to System.currentTimeMillis()
            )
            val jsonCommand = gson.toJson(command)
            pendingDesiredStates[normalizedBotName] = enable
            val sent = sendMessage(jsonCommand)
            Log.d(TAG, "Toggle bot: $botName -> ${if (enable) "START" else "STOP"}, Sent: $jsonCommand")
            scope.launch {
                if (!sent) {
                    _errors.emit("Command gagal dikirim. WebSocket belum terhubung.")
                } else {
                    delay(400)
                    requestFullState()
                    delay(1600)
                    requestFullState()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error sending toggle command: ${e.message}", e)
        }
    }

    fun requestFullState() {
        val now = System.currentTimeMillis()
        if (now - lastFullStateRequestAtMs < 800) return
        lastFullStateRequestAtMs = now
        val request = mapOf("type" to "request", "data" to "full_state")
        sendMessage(gson.toJson(request))
    }

    private fun sendMessage(json: String): Boolean {
        return webSocket?.send(json)?.also {
            Log.d(TAG, "Sent: $json")
        } ?: run {
            Log.w(TAG, "WebSocket not connected, message not sent")
            false
        }
    }

    private fun scheduleReconnect() {
        if (_connectionStatus.value == ConnectionStatus.CONNECTED || isConnecting) return
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            reconnectAttempt = (reconnectAttempt + 1).coerceAtMost(8)
            val baseMs = 1_500L
            val maxMs = 45_000L
            val expMs = (baseMs shl (reconnectAttempt - 1)).coerceAtMost(maxMs)
            val jitterMs = (Math.random() * 700L).toLong()
            val waitMs = min(expMs + jitterMs, maxMs)
            Log.w(TAG, "⏳ Reconnect attempt #$reconnectAttempt in ${waitMs}ms")
            delay(waitMs)
            Log.d(TAG, "Attempting reconnect...")
            connect()
        }
    }

    private fun startWatchdog() {
        watchdogJob?.cancel()
        watchdogJob = scope.launch {
            while (isActive && _connectionStatus.value == ConnectionStatus.CONNECTED) {
                delay(20_000)
                val now = System.currentTimeMillis()
                val staleMs = now - lastMessageAtMs
                if (staleMs > 45_000) {
                    Log.w(TAG, "🛟 WebSocket stream stale (${staleMs}ms). Forcing reconnect.")
                    webSocket?.cancel()
                    this@KiBotWebSocketClient.webSocket = null
                    _connectionStatus.value = ConnectionStatus.DISCONNECTED
                    updateBotState { it.copy(isConnected = false) }
                    scheduleReconnect()
                    break
                }
            }
        }
    }

    private fun parseMessage(text: String) {
        try {
            val json = JsonParser.parseString(text).asJsonObject
            
            // Handle server's CommandCenterWsEnvelope format: {"snapshot": {...}}
            if (json.has("snapshot")) {
                parseCommandCenterSnapshot(json.getAsJsonObject("snapshot"))
                return
            }
            if (json.has("reply")) {
                val reply = json.getAsJsonObject("reply")
                val replySnapshot = reply.getAsJsonObject("updatedSnapshot")
                val replyBotId = replySnapshot?.get("botId")?.asString?.lowercase()
                val currentConnectedBotId = _botState.value.connectedBotId.lowercase()
                if (replySnapshot != null && (
                        currentConnectedBotId == "unknown" ||
                            replyBotId == null ||
                            replyBotId == currentConnectedBotId
                    )
                ) {
                    parseCommandCenterSnapshot(replySnapshot)
                }
                reply.get("message")?.asString?.takeIf { it.isNotBlank() }?.let { message ->
                    updateBotState { currentState ->
                        currentState.copy(
                            statusMessage = message,
                            lastUpdate = System.currentTimeMillis()
                        )
                    }
                }
                reply.get("echoCommand")?.asString?.lowercase()?.let { commandName ->
                    val targetBot = replyBotId
                    if (targetBot != null) {
                        when (commandName) {
                            "/start" -> pendingDesiredStates[targetBot] = true
                            "/stop", "/pause_KiBot", "/veto_all" -> pendingDesiredStates[targetBot] = false
                        }
                    }
                }
                return
            }
            
            // Handle legacy format with "type" field
            val type = json.get("type")?.asString ?: return
            val dataElement = json.get("data")
            
            when (type) {
                "state" -> {
                    val stateData = gson.fromJson(dataElement, StateData::class.java)
                    updateBotState { currentState ->
                        currentState.copy(
                            balance = stateData.balance,
                            totalReturn = stateData.totalReturn,
                            pnlToday = stateData.pnlToday,
                            positions = stateData.positions,
                            netWorthHistory = stateData.netWorthHistory,
                            lastUpdate = System.currentTimeMillis()
                        )
                    }
                }
                
                "heartbeat" -> {
                    val heartbeatData = gson.fromJson(dataElement, HeartbeatData::class.java)
                    updateBotState { currentState ->
                        currentState.copy(
                            heartbeat = heartbeatData,
                            isConnected = true,
                            lastUpdate = System.currentTimeMillis()
                        )
                    }
                }
                
                "trade", "trades" -> {
                    val tradeData = gson.fromJson(dataElement, TradeData::class.java)
                    scope.launch {
                        _trades.emit(tradeData)
                        updateBotState { currentState ->
                            val updatedTrades = (listOf(tradeData) + currentState.trades).take(100)
                            currentState.copy(trades = updatedTrades)
                        }
                    }
                }
                
                "portfolio" -> {
                    val returnSummary = dataElement?.asJsonObject?.get("returns")?.let {
                        gson.fromJson(it, ReturnSummary::class.java)
                    } ?: ReturnSummary()
                    
                    val allocations = dataElement?.asJsonObject?.get("allocation")?.asJsonArray?.map {
                        gson.fromJson(it, AssetAllocation::class.java)
                    } ?: emptyList()
                    
                    updateBotState { currentState ->
                        currentState.copy(
                            returnSummary = returnSummary,
                            assetAllocation = allocations
                        )
                    }
                }
                
                "error" -> {
                    val errorMsg = dataElement?.asString ?: "Unknown error"
                    scope.launch { _errors.emit(errorMsg) }
                }
                
                else -> Log.d(TAG, "Unknown message type: $type")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to parse message: ${e.message}", e)
        }
    }
    
    /**
     * Parse CommandCenterLiveSnapshot from server WebSocket
     * Server sends: {"snapshot": {totalValueIdr: "Rp110.486", holdingsDetailed: [...], ...}}
     */
    private fun parseCommandCenterSnapshot(snapshot: JsonObject) {
        try {
            val currentState = _botState.value

            // Parse balance from "totalValueIdr" (format: "Rp110.486" or "Rp1.234.567")
            val totalValueIdr = snapshot.get("totalValueIdr")?.asString ?: "Rp0"
            val balance = parseRupiahToDouble(totalValueIdr)
            val freeIdr = parseRupiahToDouble(snapshot.get("freeIdrLabel")?.asString ?: "Rp0")
            
            // Parse PnL today from "pnlTodayIdr" (format: "-Rp55" or "+Rp1.234")
            val pnlTodayIdr = snapshot.get("pnlTodayIdr")?.asString ?: "Rp0"
            val pnlToday = parseRupiahToDouble(pnlTodayIdr)
            
            // Parse daily return percentage from "pnlTodayPctLabel" (format: "-0.1%" or "+29.9%")
            val pnlTodayPctLabel = snapshot.get("pnlTodayPctLabel")?.asString ?: "0%"
            val pnlTodayPercent = parsePercentToDouble(pnlTodayPctLabel)
            val return7dIdr = parseRupiahToDouble(snapshot.get("return7dIdr")?.asString ?: "Rp0")
            val return7dPct = parsePercentToDouble(snapshot.get("return7dPctLabel")?.asString ?: "0%")
            val return30dIdr = parseRupiahToDouble(snapshot.get("return30dIdr")?.asString ?: "Rp0")
            val return30dPct = parsePercentToDouble(snapshot.get("return30dPctLabel")?.asString ?: "0%")
            
            // "totalReturn" in the app now mirrors 1D return for consistency with the dashboard/widget.
            val totalReturnPctLabel = snapshot.get("totalReturnPctLabel")?.asString 
                ?: snapshot.get("cumulativeReturnPctLabel")?.asString 
                ?: pnlTodayPctLabel
            val totalReturn = parsePercentToDouble(totalReturnPctLabel)
            
            // Parse holdings from "holdingsDetailed"
            val positions = mutableListOf<Position>()
            snapshot.getAsJsonArray("holdingsDetailed")?.forEach { holdingElement ->
                val holding = holdingElement.asJsonObject
                val assetCode = holding.get("assetCode")?.asString ?: ""
                val quantityLabel = holding.get("quantityLabel")?.asString ?: "0"
                val entryPriceLabel = holding.get("entryPriceLabel")?.asString ?: "Rp0"
                val currentPriceLabel = holding.get("currentPriceLabel")?.asString ?: "Rp0"
                val valueIdrLabel = holding.get("valueIdrLabel")?.asString ?: "Rp0"
                val pnlIdrLabel = holding.get("pnlIdrLabel")?.asString ?: "Rp0"
                val pnlPctLabel = holding.get("pnlPctLabel")?.asString ?: "0%"
                
                val amount = quantityLabel.split(" ").firstOrNull()?.replace(",", ".")?.toDoubleOrNull() ?: run {
                    if (quantityLabel != "0") {
                        android.util.Log.w("KiCrypWebSocketClient", "⚠️ Failed to parse quantity from '$quantityLabel' for $assetCode")
                    }
                    0.0
                }
                val entryPrice = parseRupiahToDouble(entryPriceLabel)
                val currentPrice = parseRupiahToDouble(currentPriceLabel)
                val valueIdr = parseRupiahToDouble(valueIdrLabel)
                val pnl = parseRupiahToDouble(pnlIdrLabel)
                val pnlPercent = parsePercentToDouble(pnlPctLabel)
                
                if (assetCode.isNotEmpty() && amount > 0) {
                    positions.add(Position(
                        pair = "${assetCode.lowercase()}_idr",
                        amount = amount,
                        buyPrice = entryPrice,
                        currentPrice = currentPrice,
                        pnl = pnl,
                        pnlPercent = pnlPercent,
                        valueIdr = valueIdr
                    ))
                }
            }
            positions.sortByDescending { it.valueIdr }
            
            // Parse recent trades from "recentOrders"
            val trades = mutableListOf<TradeData>()
            snapshot.getAsJsonArray("recentOrders")?.take(20)?.forEach { orderElement ->
                val order = orderElement.asJsonObject
                val pair = order.get("pair")?.asString ?: ""
                val side = order.get("side")?.asString?.lowercase() ?: "buy"
                val status = order.get("status")?.asString?.uppercase().orEmpty()
                val orderType = order.get("orderType")?.asString?.lowercase().orEmpty()
                val detail = order.get("detail")?.asString ?: ""
                val timestampMs = order.get("timestampEpochMs")?.asLong ?: System.currentTimeMillis()
                val pnlLabel = order.get("pnlIdrLabel")?.asString
                val pnlPctLabel = order.get("pnlPctLabel")?.asString
                val entryPriceLabel = order.get("entryPriceLabel")?.asString.orEmpty()
                val exitPriceLabel = order.get("exitPriceLabel")?.asString.orEmpty()
                if (status !in setOf("FILLED", "PARTIALLY_FILLED")) return@forEach
                
                // Parse detail for price/amount.
                // Supported examples:
                // "203 @ Rp107"
                // "264.00000000 @ ~ • LIMIT"
                // "159568.00000000 @ Rp0.062700 • LIMIT"
                val amount = parseTradeAmount(detail)
                val parsedEntryPrice = entryPriceLabel.takeIf { it.isNotBlank() }?.let(::parseRupiahToDouble)
                val parsedExitPrice = exitPriceLabel.takeIf { it.isNotBlank() }?.let(::parseRupiahToDouble)
                val price = parseTradePrice(detail)
                    ?: parsedExitPrice
                    ?: parsedEntryPrice
                    ?: run {
                        0.0
                    }
                val resolvedTotal = when {
                    price > 0.0 && amount > 0.0 -> price * amount
                    parsedExitPrice != null && amount > 0.0 -> parsedExitPrice * amount
                    parsedEntryPrice != null && amount > 0.0 -> parsedEntryPrice * amount
                    else -> 0.0
                }
                
                if (pair.isNotEmpty()) {
                    trades.add(TradeData(
                        id = "${pair}_${timestampMs}",
                        pair = pair,
                        side = side,
                        status = status,
                        orderType = orderType,
                        price = price,
                        amount = amount,
                        total = resolvedTotal,
                        timestamp = timestampMs,
                        entryPrice = parsedEntryPrice,
                        exitPrice = parsedExitPrice,
                        profitLoss = pnlLabel?.takeIf { it.isNotBlank() }?.let { parseRupiahToDouble(it) },
                        profitLossPercent = pnlPctLabel?.takeIf { it.isNotBlank() }?.let(::parsePercentToDouble),
                    ))
                }
            }
            
            // Parse heartbeat/bot status
            val effectiveState = snapshot.get("effectiveState")?.asString ?: "STOPPED"
            val syncHealth = snapshot.get("syncHealth")?.asString ?: "DEGRADED"
            val exchangePingMs = snapshot.get("exchangePingValueMs")?.asLong ?: 0L
            val liveExecutionEnabled = snapshot.get("liveExecutionEnabled")?.asBoolean ?: false
            val aiProviderSummary = snapshot.get("aiProviderSummary")?.asString ?: "AI summary belum siap."
            val healthSummary = snapshot.get("healthSummary")?.asString ?: "Menunggu status server."
            val statusMessage = snapshot.get("statusMessage")?.asString ?: "Server monitor sedang booting."
            val connectedBotId = snapshot.get("botId")?.asString?.lowercase() ?: currentState.connectedBotId
            val topCandidate = snapshot.get("topCandidate")?.asString ?: currentState.topCandidate
            val radarPairs = snapshot.getAsJsonArray("radarPairs")?.mapNotNull { it.asString } ?: currentState.radarPairs
            val syncHealthStatus = syncHealth.uppercase()

            val aiStatus = deriveAiStatus(aiProviderSummary)

            val connectedEnabled = pendingDesiredStates[connectedBotId]
                ?: when (connectedBotId) {
                    "KiBot" -> liveExecutionEnabled && effectiveState != "STOPPED"
                    else -> effectiveState != "STOPPED"
                }

            val connectedService = ServiceStatus(
                status = deriveStatus(effectiveState, syncHealthStatus),
                ping = exchangePingMs,
                aiStatus = aiStatus,
                enabled = connectedEnabled,
                holdings = if (connectedBotId == "KiBot") {
                    positions.map { Holding(it.pair.split("_").first().uppercase(), it.amount, it.currentPrice, it.pnl) }
                } else {
                    emptyList()
                }
            )

            val kiBotPingMs = snapshot.get("KiBotPingMs")?.asLong
                ?: snapshot.get("KiBotLatencyMs")?.asLong
                ?: 0L

            val kiBotNodeStatus = snapshot.get("KiBotNodeStatus")?.asString ?: currentState.heartbeat.KiBot.status
            val kibotNodeStatus = snapshot.get("kibotNodeStatus")?.asString ?: currentState.heartbeat.kibot.status

            val kiBotStatus = when (connectedBotId) {
                "KiBot" -> connectedService.copy(status = kiBotNodeStatus)
                else -> currentState.heartbeat.KiBot.copy(
                    ping = kiBotPingMs,
                    status = kiBotNodeStatus,
                    aiStatus = aiStatus
                )
            }
            val kibotStatus = when (connectedBotId) {
                "kibot" -> connectedService.copy(holdings = emptyList(), status = kibotNodeStatus)
                else -> currentState.heartbeat.kibot.copy(
                    ping = currentState.heartbeat.kibot.ping,
                    status = kibotNodeStatus,
                    holdings = emptyList(),
                    aiStatus = aiStatus
                )
            }
            
            // Parse net worth history for charts
            val netWorthHistory = mutableListOf<NetWorthPoint>()
            snapshot.getAsJsonArray("netWorthHistory")?.forEach { point ->
                val pointObj = point.asJsonObject
                val timestamp = pointObj.get("timestamp")?.asLong ?: System.currentTimeMillis()
                val value = parseRupiahToDouble(pointObj.get("value")?.asString ?: "Rp0")
                netWorthHistory.add(NetWorthPoint(timestamp, value))
            }
            
            // If no history provided, add current balance as baseline
            if (netWorthHistory.isEmpty()) {
                netWorthHistory.add(NetWorthPoint(System.currentTimeMillis(), balance))
            }
            
            // Parse asset allocation details for pie chart
            val assetAllocations = mutableListOf<AssetAllocation>()
            snapshot.getAsJsonArray("assetAllocationDetailed")?.forEach { item ->
                val obj = item.asJsonObject
                val coin = obj.get("coin")?.asString ?: ""
                val percentageLabel = obj.get("percentageLabel")?.asString ?: "0%"
                val valueLabel = obj.get("valueLabel")?.asString ?: "Rp0"
                
                if (coin.isNotEmpty()) {
                    assetAllocations.add(AssetAllocation(
                        coin = coin,
                        percentage = parsePercentToDouble(percentageLabel),
                        value = parseRupiahToDouble(valueLabel)
                    ))
                }
            }
            
            // If no allocations provided, derive from positions + free cash
            if (assetAllocations.isEmpty() && (positions.isNotEmpty() || balance > 0)) {
                val cryptoValue = positions.sumOf { it.currentPrice * it.amount }
                val freeIdrValue = freeIdr.takeIf { it > 0.0 } ?: (balance - cryptoValue).coerceAtLeast(0.0)
                val totalPortfolio = maxOf(balance, cryptoValue + freeIdrValue)
                
                // Add free cash (IDR) first
                if (freeIdrValue > 0 && totalPortfolio > 0) {
                    val cashPct = (freeIdrValue / totalPortfolio) * 100
                    assetAllocations.add(AssetAllocation(
                        coin = "IDR",
                        percentage = cashPct,
                        value = freeIdrValue
                    ))
                }
                
                // Add crypto positions
                positions.forEach { pos ->
                    val value = pos.currentPrice * pos.amount
                    val pct = if (totalPortfolio > 0) (value / totalPortfolio) * 100 else 0.0
                    assetAllocations.add(AssetAllocation(
                        coin = pos.pair.split("_").first().uppercase(),
                        percentage = pct,
                        value = value
                    ))
                }
            } else if (assetAllocations.isNotEmpty()) {
                // Allocations exist from server, but ensure cash/IDR is included
                val hasCash = assetAllocations.any { it.coin.uppercase() == "IDR" || it.coin.uppercase() == "CASH" }
                if (!hasCash && (freeIdr > 0.0 || balance > 0.0)) {
                    val cryptoValue = positions.sumOf { it.currentPrice * it.amount }
                    val freeIdrValue = freeIdr.takeIf { it > 0.0 } ?: (balance - cryptoValue).coerceAtLeast(0.0)
                    if (freeIdrValue > 0) {
                        val totalPortfolio = maxOf(balance, cryptoValue + freeIdrValue)
                        val cashPct = (freeIdrValue / totalPortfolio) * 100
                        assetAllocations.add(0, AssetAllocation(
                            coin = "IDR",
                            percentage = cashPct,
                            value = freeIdrValue
                        ))
                    }
                }
            }
            
            val authoritativeBundle =
                balance > 0.0 ||
                    positions.isNotEmpty() ||
                    trades.isNotEmpty() ||
                    assetAllocations.isNotEmpty() ||
                    netWorthHistory.size > 1
            val bootLikeSnapshot =
                effectiveState in listOf("STOPPED", "DEGRADED") ||
                    syncHealthStatus in listOf("DEGRADED", "BROKEN") ||
                    aiProviderSummary.contains("OFFLINE", ignoreCase = true) ||
                    healthSummary.contains("sync", ignoreCase = true) ||
                    healthSummary.contains("lease", ignoreCase = true) ||
                    statusMessage.contains("boot", ignoreCase = true)
            val preserveBundle = bootLikeSnapshot && !authoritativeBundle
            val KiBotPrimarySnapshot = connectedBotId == "KiBot"
            val keepExistingFinancials = preserveBundle || (!KiBotPrimarySnapshot && !authoritativeBundle)
            val nextBalance = if (keepExistingFinancials) currentState.balance else balance
            val nextPnlToday = pnlToday  // Always update PnL from server
            val nextTotalReturn = totalReturn  // Always update Total Return from server (now mirrors PnL)
            val nextPositions = if (keepExistingFinancials) currentState.positions else positions
            val nextTrades = if (keepExistingFinancials) currentState.trades else trades
            val nextHistory = if (keepExistingFinancials) currentState.netWorthHistory else netWorthHistory
            val nextAllocations = if (keepExistingFinancials) currentState.assetAllocation else assetAllocations

            updateBotState { currentState ->
                currentState.copy(
                    balance = nextBalance,
                    totalReturn = nextTotalReturn,
                    pnlToday = nextPnlToday,
                    pnlTodayPercent = pnlTodayPercent,
                    positions = nextPositions,
                    trades = nextTrades,
                    topCandidate = topCandidate,
                    radarPairs = radarPairs,
                    heartbeat = HeartbeatData(
                        KiBot = kiBotStatus,
                        kibot = kibotStatus
                    ),
                    returnSummary = ReturnSummary(
                        day1 = pnlTodayPercent,
                        day7 = return7dPct,
                        day30 = return30dPct,
                        day1Idr = pnlToday,
                        day7Idr = return7dIdr,
                        day30Idr = return30dIdr,
                    ),
                    netWorthHistory = nextHistory,
                    assetAllocation = nextAllocations,
                    effectiveState = effectiveState,
                    syncHealth = syncHealth,
                    aiProviderSummary = aiProviderSummary,
                    healthSummary = healthSummary,
                    statusMessage = statusMessage,
                    lastActivityUpdate = System.currentTimeMillis(),
                    connectedBotId = connectedBotId,
                    isConnected = true,
                    lastUpdate = System.currentTimeMillis(),
                    whatIfSimulation = snapshot.get("whatIfSimulation")?.takeIf { !it.isJsonNull }?.let {
                        gson.fromJson(it, SimulationSummary::class.java)
                    },
                    tradeHistory = snapshot.get("tradeHistory")?.takeIf { !it.isJsonNull }?.let {
                        gson.fromJson(it, TradeHistorySummary::class.java)
                    }
                )
            }
            
            Log.d(TAG, "Parsed snapshot: balance=$balance, totalReturn=$totalReturn%, pnlToday=$pnlToday (${pnlTodayPercent}%), " +
                "positions=${positions.size}, trades=${trades.size}, allocations=${assetAllocations.size}")
            
        } catch (e: Exception) {
            Log.e(TAG, "Failed to parse CommandCenter snapshot: ${e.message}", e)
        }
    }
    
    /**
     * Parse Indonesian Rupiah format to Double
     * Examples: "Rp110.486" -> 110486.0, "-Rp55" -> -55.0, "+Rp1.234.567" -> 1234567.0
     */
    private fun parseRupiahToDouble(value: String): Double {
        if (value.isBlank()) {
            android.util.Log.w("KiCrypWebSocketClient", "⚠️ parseRupiahToDouble: Empty input")
            return 0.0
        }
        
        val isNegative = value.startsWith("-")
        val raw = value
            .replace("Rp", "")
            .replace("+", "")
            .replace("-", "")
            .trim()

        val cleaned = when {
            raw.contains(',') && raw.contains('.') -> raw.replace(".", "").replace(",", ".")
            raw.contains(',') -> raw.replace(",", ".")
            raw.contains('.') -> {
                val fractionalGroups = raw.split('.').drop(1)
                val looksLikeThousands = fractionalGroups.isNotEmpty() && fractionalGroups.all { it.length == 3 }
                if (looksLikeThousands) raw.replace(".", "") else raw
            }
            else -> raw
        }

        val result = cleaned.toDoubleOrNull()
        if (result == null) {
            android.util.Log.w("KiCrypWebSocketClient", "⚠️ parseRupiahToDouble: Failed to parse '$value' -> '$cleaned'")
            return 0.0
        }
        
        return if (isNegative) -result else result
    }
    
    /**
     * Parse percentage format to Double
     * Examples: "-0.1%" -> -0.1, "+29.9%" -> 29.9
     */
    private fun parsePercentToDouble(value: String): Double {
        if (value.isBlank() || value == "0%" || value == "0.00%") {
            return 0.0
        }
        
        val cleaned = value
            .replace("%", "")
            .replace(",", ".")
            .trim()
        
        val result = cleaned.toDoubleOrNull()
        if (result == null) {
            android.util.Log.w("KiCrypWebSocketClient", "⚠️ parsePercentToDouble: Failed to parse '$value' -> '$cleaned'")
            return 0.0
        }
        
        return result
    }

    private fun parseTradeAmount(detail: String): Double {
        if (detail.isBlank()) return 0.0
        val amountToken = detail.substringBefore("@", detail)
            .substringBefore("•")
            .trim()
        val amount = amountToken.replace(",", ".").toDoubleOrNull()
        if (amount == null && amountToken.isNotBlank() && amountToken != "~") {
            android.util.Log.w("KiCrypWebSocketClient", "⚠️ Failed to parse amount from trade detail: '$detail'")
        }
        return amount ?: 0.0
    }

    private fun parseTradePrice(detail: String): Double? {
        if (detail.isBlank() || !detail.contains("@")) return null
        val priceToken = detail.substringAfter("@", "")
            .substringBefore("•")
            .trim()
        if (priceToken.isBlank() || priceToken == "~") return null
        return parseRupiahToDouble(priceToken).takeIf { it > 0.0 }
    }

    private inline fun updateBotState(update: (BotState) -> BotState) {
        _botState.value = update(_botState.value)
    }

    private fun deriveStatus(currentEffectiveState: String, currentSyncHealth: String): String = when {
        currentEffectiveState == "STOPPED" -> "offline"
        currentSyncHealth == "BROKEN" -> "degraded"
        currentEffectiveState == "DEGRADED" || currentSyncHealth == "DEGRADED" -> "degraded"
        else -> "online"
    }

    private fun deriveAiStatus(aiProviderSummary: String): String = when {
        aiProviderSummary.contains("OFFLINE", ignoreCase = true) -> "offline"
        aiProviderSummary.contains("LIMITED", ignoreCase = true) -> "limited"
        aiProviderSummary.contains("ONLINE", ignoreCase = true) -> "active"
        else -> "offline"  // Default to offline for unknown/default states
    }

    private inner class KiBotWebSocketListener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
            Log.i(TAG, "✅ WebSocket CONNECTED to $wsUrl")
            isConnecting = false
            reconnectJob?.cancel()
            reconnectJob = null
            reconnectAttempt = 0
            lastMessageAtMs = System.currentTimeMillis()
            _connectionStatus.value = ConnectionStatus.CONNECTED
            updateBotState { it.copy(isConnected = true) }
            startWatchdog()
            
            // Subscribe to channels
            subscribe()
            
            // Request initial state
            requestFullState()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            Log.i(TAG, "📥 Received message: ${text.take(150)}...")
            parseMessage(text)
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            Log.i(TAG, "📥 Received binary: ${bytes.size} bytes")
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            Log.w(TAG, "⚠️ WebSocket closing: $code - $reason")
            webSocket.close(1000, null)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            Log.w(TAG, "❌ WebSocket closed: $code - $reason")
            this@KiBotWebSocketClient.webSocket = null
            watchdogJob?.cancel()
            _connectionStatus.value = ConnectionStatus.DISCONNECTED
            updateBotState { it.copy(isConnected = false) }
            
            if (code != 1000) {
                scheduleReconnect()
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: okhttp3.Response?) {
            Log.e(TAG, "🚨 WebSocket FAILURE: ${t.message}", t)
            isConnecting = false
            this@KiBotWebSocketClient.webSocket = null
            watchdogJob?.cancel()
            _connectionStatus.value = ConnectionStatus.ERROR
            updateBotState { it.copy(isConnected = false) }
            
            scope.launch { _errors.emit("Connection lost: ${t.message}") }
            advanceTargetIfNeeded()
            scheduleReconnect()
        }
    }

    companion object {
        private const val TAG = "KiBotWebSocket"
    }

    private fun buildConnectionTargets(url: String): List<String> {
        val normalized = url.trim()
        if (normalized.isBlank()) return ServerConfig().getConnectionUrls()

        val token = Uri.parse(normalized).getQueryParameter("token").orEmpty()
        val proxyTunnelUrl = ServerConfig.buildUrl(
            ServerConfig.TUNNEL_HOST,
            ServerConfig.PROXY_TUNNEL_PORT,
            token
        )
        val directTunnelUrl = ServerConfig.buildUrl(
            ServerConfig.TUNNEL_HOST,
            ServerConfig.DIRECT_TUNNEL_PORT,
            token
        )
        return listOf(proxyTunnelUrl, directTunnelUrl, normalized).distinct()
    }

    private fun advanceTargetIfNeeded() {
        if (connectionTargets.size <= 1) return
        activeTargetIndex = (activeTargetIndex + 1) % connectionTargets.size
        wsUrl = connectionTargets[activeTargetIndex]
        reconnectAttempt = 0
        Log.w(TAG, "🛟 Switching WebSocket target to fallback: $wsUrl")
    }
}

// Legacy compatibility adapter
class LegacyWebSocketAdapter(
    wsUrl: String,
    private val onStatusUpdate: (BotStatus) -> Unit,
    private val onConnectionChange: (Boolean) -> Unit,
    private val onError: (String) -> Unit
) {
    private val client = KiBotWebSocketClient(wsUrl)
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    
    init {
        scope.launch {
            client.connectionStatus.collect { status ->
                onConnectionChange(status == ConnectionStatus.CONNECTED)
            }
        }
        
        scope.launch {
            client.botState.collect { state ->
                val legacyStatus = BotStatus(
                    balance = Balance(
                        idr = state.balance,
                        usdt = state.balance / 16000.0,
                        total = state.balance
                    ),
                    pnl = PnL(
                        daily = state.pnlToday,
                        percentage = state.totalReturn,
                        trend = state.netWorthHistory.takeLast(24).map { it.value }
                    ),
                    capitalSplit = CapitalSplit(
                        highConviction = state.balance * 0.7,
                        aggressive = state.balance * 0.3
                    ),
                    activeTrades = state.positions.map { pos ->
                        Trade(
                            pair = pos.pair,
                            entry = pos.buyPrice,
                            current = pos.currentPrice,
                            profit = pos.pnl,
                            profitPct = pos.pnlPercent
                        )
                    },
                    status = if (state.isConnected) "Trading" else "Stopped",
                    timestamp = state.lastUpdate
                )
                onStatusUpdate(legacyStatus)
            }
        }
        
        scope.launch {
            client.errors.collect { error ->
                onError(error)
            }
        }
    }
    
    fun connect() = client.connect()
    fun disconnect() = client.disconnect()
    fun requestStatus() = client.requestFullState()
    fun sendCommand(command: String) {
        when (command) {
            "start" -> client.toggleBot("all", true)
            "stop" -> client.toggleBot("all", false)
        }
    }
}
