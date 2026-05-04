package com.kibot.macengine.runtime

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.datetime.Instant

internal enum class UdpBinaryMessageType(val code: Byte, val wireMsgType: String) {
    HEARTBEAT(1, "HEARTBEAT"),
    DETECTOR_HIT(10, "DETECTOR_HIT"),
    INSTANT_BUY_ANOMALY(11, "INSTANT_BUY_ANOMALY"),
    VETO_APPROVED(12, "VETO_APPROVED"),
    VETO_REJECTED(13, "VETO_REJECTED"),
    VETO_SELL_CONFIRMED(14, "VETO_SELL_CONFIRMED"),
    EMERGENCY_VETO_SELL(15, "EMERGENCY_VETO_SELL"),
    SELL_WALL_SURGE(16, "SELL_WALL_SURGE"),
    MOMENTUM_LOSS(17, "MOMENTUM_LOSS"),
    ORDERBOOK_COLLAPSE(18, "ORDERBOOK_COLLAPSE"),
    POLYMARKET_SENTIMENT(20, "POLYMARKET_SENTIMENT"),
    UNKNOWN(127, "UNKNOWN");

    companion object {
        fun fromCode(code: Byte): UdpBinaryMessageType = entries.firstOrNull { it.code == code } ?: UNKNOWN
        fun fromMsgType(msgType: String): UdpBinaryMessageType = entries.firstOrNull {
            it.wireMsgType.equals(msgType, ignoreCase = true)
        } ?: UNKNOWN
    }
}

@Serializable
internal data class LeadLagCalloutPayload(
    val kind: String = "lead_lag_breakout",
    val msgType: String = "DETECTOR_HIT",
    val traceId: String,
    val senderBotId: String,
    val pairId: String,
    val trend: String = "UP",
    val detectedAtEpochMs: Long,
    val confidence: Double,
    val expectedNetPct: Double,
    val shortTermReturnPct: Double,
    val mediumTermReturnPct: Double,
    val tradeActivityScore: Double,
    val forceRotation: Boolean = true,
    val sentAtEpochMs: Long,
    val expiresAtEpochMs: Long,
    val payload: JsonObject? = null,
)

@Serializable
internal data class TrinityHeartbeatPayload(
    val kind: String = "trinity_state",
    val msgType: String = "HEARTBEAT",
    val senderBotId: String,
    val sentAtEpochMs: Long,
    val activePair: String? = null,
    val safeModeArmed: Boolean = false,
)

@Serializable
internal data class PolymarketSentimentPayload(
    val kind: String = "polymarket_sentiment",
    val msgType: String = "POLYMARKET_SENTIMENT",
    val pairId: String,
    val sentimentScore: Double, // -1.0 to 1.0
    val bias: String, // "BULLISH", "BEARISH", "NEUTRAL"
    val volume24h: Double,
    val sentAtEpochMs: Long,
)

internal data class DecodedUdpPacket(
    val heartbeat: TrinityHeartbeatPayload? = null,
    val leadLag: LeadLagCalloutPayload? = null,
    val sentiment: PolymarketSentimentPayload? = null,
    val senderBotId: String? = null,
    val sequenceId: Int? = null,
    val dedupKey: String? = null,
    val binary: Boolean = false,
)
