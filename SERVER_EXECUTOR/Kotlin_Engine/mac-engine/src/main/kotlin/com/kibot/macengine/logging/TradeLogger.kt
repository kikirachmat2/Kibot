package com.kibot.macengine.logging

import com.kibot.core.AtomicFileWriter
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.time.Instant
import java.time.ZoneId

@Serializable
data class TradeRecord(
    val id: String,                    // UUID
    val timestamp: String,             // ISO-8601 UTC
    val pair: String,                  // "fartcoin_idr"
    val side: String,                  // "BUY" or "SELL"
    val orderType: String,             // "LIMIT" or "MARKET"
    val requestedPrice: Double,
    val filledPrice: Double,
    val filledAmount: Double,          // base currency amount
    val filledIdr: Double,             // IDR value of fill
    val feeIdr: Double,
    val feeType: String,               // "MAKER" or "TAKER"
    val grossPnlPct: Double,           // null for BUY entries
    val netPnlPct: Double,             // after fee
    val netPnlIdr: Double,
    val holdingDurationMs: Long,       // 0 for BUY
    val exitReason: String,            // "TRAILING_STOP", "TAKE_PROFIT", "TIME_EXIT", "EMERGENCY", "MANUAL"
    val signalSource: String,          // "LEAD_LAG", "VWAP", "SCANNER", "MANUAL"
    val entryScore: Double,            // 11-point score saat entry
    val balanceAfter: Double,          // IDR balance setelah trade
    val marketRegime: String,          // "BULLISH", "BEARISH", "SIDEWAYS"
    val notes: String = ""
)

object TradeLogger {
    private val logPath = File("state/trade_log.jsonl")
    private val analystMirrorPath = File("state/analyst/trade_log.jsonl")
    private val summaryPath = File("state/trade_summary.json")
    private val json = Json { ignoreUnknownKeys = true }
    private val wibZone: ZoneId = ZoneId.of("Asia/Jakarta")

    init {
        logPath.parentFile?.mkdirs()
        analystMirrorPath.parentFile?.mkdirs()
    }

    fun record(trade: TradeRecord) {
        try {
            val normalized = normalize(trade)
            val encoded = json.encodeToString(normalized) + "\n"
            logPath.appendText(encoded)
            analystMirrorPath.appendText(encoded)
            
            // [ANOMALY DETECTION] Check for excessive slippage
            checkSlippageAnomaly(normalized)
            
            updateSummary(normalized)
        } catch (e: Exception) {
            System.err.println("[TRADE_LOGGER] Failed to write trade: ${e.message}")
        }
    }

    private fun checkSlippageAnomaly(trade: TradeRecord) {
        if (trade.requestedPrice <= 0.0 || trade.filledPrice <= 0.0) return
        
        val slippagePct = if (trade.side == "BUY") {
            ((trade.filledPrice - trade.requestedPrice) / trade.requestedPrice) * 100.0
        } else {
            ((trade.requestedPrice - trade.filledPrice) / trade.requestedPrice) * 100.0
        }

        if (slippagePct >= 0.5) { // 0.5% slippage is an anomaly in high-liquidity zones
            System.err.println("[ANOMALY] High slippage detected on ${trade.pair}: ${String.format("%.3f", slippagePct)}%")
            // In the future, this could emit an event to the Governor
        }
    }

    fun getTodayTrades(): List<TradeRecord> {
        val today = Instant.now().atZone(wibZone).toLocalDate()
        return readAll().filter { trade ->
            runCatching { Instant.parse(trade.timestamp).atZone(wibZone).toLocalDate() == today }.getOrDefault(false)
        }
    }

    fun getLast7DaysTrades(): List<TradeRecord> {
        val cutoff = Instant.now().minusSeconds(7 * 86400).toString()
        return readAll().filter { it.timestamp >= cutoff }
    }

    fun getLast30DaysTrades(): List<TradeRecord> {
        val cutoff = Instant.now().minusSeconds(30 * 86400).toString()
        return readAll().filter { it.timestamp >= cutoff }
    }

    fun readAll(): List<TradeRecord> {
        if (!logPath.exists()) return emptyList()
        return logPath.readLines()
            .filter { it.isNotBlank() }
            .mapNotNull { runCatching { json.decodeFromString<TradeRecord>(it) }.getOrNull() }
    }

    private fun normalize(trade: TradeRecord): TradeRecord {
        val normalizedFilledPrice = when {
            trade.filledPrice > 0.0 -> trade.filledPrice
            trade.requestedPrice > 0.0 -> trade.requestedPrice
            trade.filledAmount > 0.0 && trade.filledIdr > 0.0 -> trade.filledIdr / trade.filledAmount
            else -> 0.0
        }
        val normalizedFilledIdr = when {
            trade.filledIdr > 0.0 -> trade.filledIdr
            normalizedFilledPrice > 0.0 && trade.filledAmount > 0.0 -> normalizedFilledPrice * trade.filledAmount
            else -> 0.0
        }
        return trade.copy(
            filledPrice = normalizedFilledPrice,
            filledIdr = normalizedFilledIdr,
        )
    }

    private fun updateSummary(trade: TradeRecord) {
        // Hitung rolling summary: today, 7D, 30D
        val today = getTodayTrades()
        val week = getLast7DaysTrades()
        val month = getLast30DaysTrades()

        fun stats(trades: List<TradeRecord>) = mapOf(
            "count" to trades.size,
            "winCount" to trades.count { it.netPnlPct > 0 },
            "lossCount" to trades.count { it.netPnlPct <= 0 },
            "totalNetPnlPct" to trades.sumOf { it.netPnlPct },
            "totalNetPnlIdr" to trades.sumOf { it.netPnlIdr },
            "totalFeeIdr" to trades.sumOf { it.feeIdr },
            "marketOrderCount" to trades.count { it.orderType == "MARKET" },
            "avgHoldingMs" to if (trades.isEmpty()) 0L else
                trades.filter { it.holdingDurationMs > 0 }.map { it.holdingDurationMs }.average().toLong(),
            "topLosers" to trades.filter { it.netPnlPct <= 0 }
                .sortedBy { it.netPnlPct }.take(5)
                .map { mapOf("pair" to it.pair, "pnl" to it.netPnlPct, "reason" to it.exitReason) }
        )

        val summary = mapOf(
            "lastUpdated" to Instant.now().toString(),
            "today" to stats(today),
            "last7Days" to stats(week),
            "last30Days" to stats(month)
        )
        AtomicFileWriter.write(summaryPath, json.encodeToString(summary))
    }
}
