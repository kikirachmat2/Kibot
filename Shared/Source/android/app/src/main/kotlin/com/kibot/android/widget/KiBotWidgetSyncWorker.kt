package com.kibot.android.widget

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.google.gson.JsonParser
import com.kibot.android.data.BotState
import com.kibot.android.data.HeartbeatData
import com.kibot.android.data.ServerConfig
import com.kibot.android.data.ServiceStatus
import com.kibot.android.util.PreferencesManager
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

class KiBotWidgetSyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    private val preferencesManager = PreferencesManager(appContext)
    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .build()

    override suspend fun doWork(): Result {
        val serverConfig = preferencesManager.getServerConfig()
        val apiUrl = "http://${serverConfig.host}:${serverConfig.port}/api/state"
        val request = Request.Builder()
            .url(apiUrl)
            .get()
            .build()
        return runCatching {
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return Result.retry()
                val body = response.body?.string().orEmpty()
                if (body.isBlank()) return Result.retry()
                val json = JsonParser.parseString(body).asJsonObject
                val botState = BotState(
                    balance = parseRupiah(json.get("portfolioValueIdr")?.asString ?: "Rp0"),
                    totalReturn = parsePercent(json.get("totalReturnPctLabel")?.asString ?: "0%"),
                    pnlToday = parseRupiah(json.get("pnlTodayIdr")?.asString ?: "Rp0"),
                    heartbeat = HeartbeatData(
                        KiBot = ServiceStatus(
                            status = json.get("KiBotNodeStatus")?.asString ?: "offline",
                            ping = json.get("exchangePingValueMs")?.asLong ?: 0L,
                        ),
                        kibot = ServiceStatus(
                            status = json.get("kibotNodeStatus")?.asString ?: "offline",
                            ping = 0L,
                        ),
                    ),
                    connectedBotId = "KiBot",
                    syncHealth = json.get("syncHealth")?.asString ?: "DEGRADED",
                    effectiveState = json.get("effectiveState")?.asString ?: "STOPPED",
                    aiProviderSummary = json.get("aiProviderSummary")?.asString ?: "",
                    healthSummary = json.get("healthSummary")?.asString ?: "",
                    statusMessage = json.get("statusMessage")?.asString ?: "",
                    isConnected = true,
                    lastUpdate = System.currentTimeMillis(),
                )
                KiBotWidgetHelper.updateWidgetData(applicationContext, botState)
                Result.success()
            }
        }.getOrElse { Result.retry() }
    }

    private fun parseRupiah(label: String): Double {
        val cleaned = label.replace("Rp", "", ignoreCase = true)
            .replace(".", "")
            .replace(",", ".")
            .replace("+", "")
            .trim()
        return cleaned.toDoubleOrNull() ?: 0.0
    }

    private fun parsePercent(label: String): Double {
        return label.replace("%", "")
            .replace(",", ".")
            .replace("+", "")
            .trim()
            .toDoubleOrNull()
            ?: 0.0
    }
}
