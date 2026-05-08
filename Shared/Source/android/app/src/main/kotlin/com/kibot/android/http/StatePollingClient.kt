package com.kibot.android.http

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonParser
import com.kibot.android.data.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * HTTP polling client for state updates when WebSocket is unavailable.
 * Polls /api/state endpoint every 2 seconds as fallback.
 */
class StatePollingClient(wsUrl: String) {
    // Convert ws:// to http://, remove /ws path if present
    private val baseUrl = wsUrl
        .replace("ws://", "http://")
        .replace("wss://", "https://")
        .substringBefore("?")
        .substringBefore("/ws")
        .trimEnd('/')
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()
    
    private val gson = Gson()
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    private val _connectionStatus = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    val connectionStatus: StateFlow<ConnectionStatus> = _connectionStatus
    
    private val _botState = MutableStateFlow(BotState())
    val botState: StateFlow<BotState> = _botState
    
    private val _errors = MutableSharedFlow<String>()
    val errors: SharedFlow<String> = _errors
    
    private var pollingJob: Job? = null
    private var isRunning = false
    private var consecutiveFailures = 0
    
    private companion object {
        const val TAG = "StatePollingClient"
        const val POLL_INTERVAL_MS = 2000L
        const val MAX_CONSECUTIVE_FAILURES = 5
    }
    
    fun start() {
        if (isRunning) {
            Log.w(TAG, "⚠️ Polling already running")
            return
        }
        
        isRunning = true
        _connectionStatus.value = ConnectionStatus.CONNECTING
        consecutiveFailures = 0
        
        pollingJob = scope.launch {
            Log.i(TAG, "🔄 Starting HTTP polling: $baseUrl/api/state")
            while (isActive && isRunning) {
                try {
                    pollState()
                    delay(POLL_INTERVAL_MS)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    Log.e(TAG, "❌ Polling error: ${e.message}", e)
                    _errors.emit("Polling error: ${e.message}")
                    delay(1000) // brief backoff
                }
            }
        }
    }
    
    fun stop() {
        if (!isRunning) return
        isRunning = false
        pollingJob?.cancel()
        pollingJob = null
        _connectionStatus.value = ConnectionStatus.DISCONNECTED
        Log.i(TAG, "⏹️ Polling stopped")
    }
    
    private suspend fun pollState() {
        val url = "$baseUrl/api/state"
        try {
            val request = Request.Builder()
                .url(url)
                .get()
                .build()
            
            val response = client.newCall(request).execute()
            
            when {
                response.isSuccessful -> {
                    val body = response.body?.string() ?: "{}"
                    val json = JsonParser.parseString(body).asJsonObject
                    
                    if (json.get("ok")?.asBoolean == true) {
                        // Parse state from /api/state response
                        val state = BotState(
                            balance = json.get("capital_health")
                                ?.asJsonObject
                                ?.get("total_equity_est_idr")
                                ?.asDouble ?: 0.0,
                            pnlToday = json.get("daily_pnl_pct")?.asDouble ?: 0.0,
                            pnlTodayPercent = json.get("daily_pnl_pct")?.asDouble ?: 0.0,
                            effectiveState = json.get("effectiveState")?.asString ?: "STOPPED",
                            statusMessage = json.get("statusMessage")?.asString ?: "Connected",
                            syncHealth = json.get("nodeStatus")?.asString ?: "active",
                            isConnected = true
                        )
                        
                        _botState.value = state
                        _connectionStatus.value = ConnectionStatus.CONNECTED
                        consecutiveFailures = 0
                        Log.d(TAG, "✅ State updated: balance=${state.balance}, status=${state.statusMessage}")
                    } else {
                        throw Exception("Invalid response: ok=false")
                    }
                }
                response.code == 408 || response.code == 504 -> {
                    consecutiveFailures++
                    _connectionStatus.value = ConnectionStatus.CONNECTING
                    Log.w(TAG, "⏳ Server timeout ($consecutiveFailures/$MAX_CONSECUTIVE_FAILURES)")
                    if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                        _errors.emit("Server not responding")
                        stop()
                    }
                }
                else -> {
                    consecutiveFailures++
                    Log.w(TAG, "❌ HTTP ${response.code} ($consecutiveFailures/$MAX_CONSECUTIVE_FAILURES)")
                    _connectionStatus.value = ConnectionStatus.CONNECTING
                    if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                        _errors.emit("Server HTTP error: ${response.code}")
                        stop()
                    }
                }
            }
            
            response.close()
        } catch (e: Exception) {
            consecutiveFailures++
            Log.e(TAG, "❌ Poll failed: ${e.message} ($consecutiveFailures/$MAX_CONSECUTIVE_FAILURES)")
            _connectionStatus.value = ConnectionStatus.CONNECTING
            
            if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                _errors.emit("Connection failed: ${e.message}")
                stop()
            }
        }
    }
}
