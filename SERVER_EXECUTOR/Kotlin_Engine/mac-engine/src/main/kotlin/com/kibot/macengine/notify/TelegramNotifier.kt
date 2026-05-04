package com.kibot.macengine.notify

import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.time.Duration
import java.util.concurrent.CompletableFuture

class TelegramNotifier(
    private val botToken: String?,
    private val chatId: String?,
    private val tradeAlertsEnabled: Boolean,
    private val minExitAlertProfitPct: Double,
    private val minExitAlertProfitIdr: Double,
) {
    private val enabled = !botToken.isNullOrBlank() && !chatId.isNullOrBlank()
    private val httpClient: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(8))
        .build()

    fun sendProfitAlert(
        pair: String,
        engineType: String,
        profitPct: Double,
        profitIdr: Double,
        bucketType: String,
    ) {
        if (!tradeAlertsEnabled) return
        if (!enabled) return
        val text = buildString {
            appendLine("📈 TP ${pair.uppercase()}")
            appendLine("PnL: ${if (profitPct >= 0) "+" else ""}${"%.2f".format(profitPct)}% | Rp ${"%.0f".format(profitIdr)}")
            append("Mode: $engineType / $bucketType")
        }
        sendAsync(text)
    }

    fun sendExecutionSellAlert(
        pair: String,
        reason: String,
        pnlIdr: Double?,
        pnlPct: Double?,
    ) {
        if (!tradeAlertsEnabled) return
        if (!enabled) return
        val profitIdr = pnlIdr ?: 0.0
        val profitPct = pnlPct ?: 0.0
        val isLossOrCut = profitIdr < 0.0 || reason.contains("cut loss", ignoreCase = true) ||
            reason.contains("stop loss", ignoreCase = true) || reason.contains("force sell", ignoreCase = true)
        val isMeaningfulProfit = profitIdr >= minExitAlertProfitIdr || profitPct >= minExitAlertProfitPct
        if (!isLossOrCut && !isMeaningfulProfit) return
        val mood = when {
            profitIdr > 0.0 -> "💰 SELL PROFIT"
            profitIdr < 0.0 -> "🛑 CUT LOSS"
            else -> "📤 EXIT"
        }
        val text = buildString {
            appendLine("$mood ${pair.uppercase()}")
            appendLine(
                when {
                    pnlIdr == null -> "PnL: ?"
                    pnlPct != null -> "PnL: ${if (profitIdr >= 0) "+" else ""}${"%.2f".format(pnlPct)}% | Rp ${"%.0f".format(kotlin.math.abs(profitIdr))}"
                    else -> "PnL: ${if (profitIdr >= 0) "+" else "-"}Rp ${"%.0f".format(kotlin.math.abs(profitIdr))}"
                }
            )
            append("Alasan: ${reason.trim().take(60)}")
        }
        sendAsync(text)
    }

    fun sendMessage(message: String) {
        if (!enabled) return
        sendAsync(message.take(3500))
    }

    fun sendStatusCard(
        title: String,
        timeLabel: String,
        balanceLabel: String,
        line1: String,
        line2: String,
        statusLabel: String,
    ) {
        if (!enabled) return
        val text = buildString {
            appendLine("🚀 $title")
            appendLine("⏰ $timeLabel | 💰 $balanceLabel")
            appendLine(line1)
            appendLine(line2)
            append("✅ $statusLabel")
        }
        sendAsync(text)
    }

    fun sendDailyReport(
        title: String,
        tradesLabel: String,
        winRateLabel: String,
        pnlLabel: String,
    ) {
        if (!enabled) return
        val text = buildString {
            appendLine("📊 $title")
            appendLine("Trades: $tradesLabel")
            appendLine("Win rate: $winRateLabel")
            append("PnL: $pnlLabel")
        }
        sendAsync(text)
    }

    private fun sendAsync(message: String) {
        val token = botToken ?: return
        val chat = chatId ?: return
        val encoded = URLEncoder.encode(message, StandardCharsets.UTF_8)
        val url = "https://api.telegram.org/bot${token}/sendMessage?chat_id=${chat}&text=${encoded}"

        val request = HttpRequest.newBuilder()
            .uri(URI.create(url))
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()

        CompletableFuture.runAsync {
            runCatching {
                httpClient.send(request, HttpResponse.BodyHandlers.discarding())
            }
        }
    }

    companion object {
        fun fromEnv(): TelegramNotifier = TelegramNotifier(
            botToken = System.getenv("KIBOT_TELEGRAM_BOT_TOKEN")
                ?: System.getenv("TELEGRAM_BOT_TOKEN")
                ?: System.getenv("KICRYP_TELEGRAM_BOT_TOKEN"),
            chatId = System.getenv("KIBOT_TELEGRAM_CHAT_ID")
                ?: System.getenv("TELEGRAM_CHAT_ID")
                ?: System.getenv("KICRYP_TELEGRAM_CHAT_ID"),
            tradeAlertsEnabled = (System.getenv("KIBOT_TELEGRAM_TRADE_ALERTS_ENABLED")
                ?: System.getenv("KICRYP_TELEGRAM_TRADE_ALERTS_ENABLED"))
                ?.equals("true", ignoreCase = true)
                ?: false,
            minExitAlertProfitPct = (System.getenv("KIBOT_TELEGRAM_MIN_EXIT_ALERT_PROFIT_PCT")
                ?: System.getenv("KICRYP_TELEGRAM_MIN_EXIT_ALERT_PROFIT_PCT"))
                ?.toDoubleOrNull()
                ?: 1.5,
            minExitAlertProfitIdr = (System.getenv("KIBOT_TELEGRAM_MIN_EXIT_ALERT_PROFIT_IDR")
                ?: System.getenv("KICRYP_TELEGRAM_MIN_EXIT_ALERT_PROFIT_IDR"))
                ?.toDoubleOrNull()
                ?: 20_000.0,
        )
    }
}
