package com.kibot.macengine.runtime

import kotlinx.serialization.Serializable

@Serializable
data class LeadLagAckPayload(
    val kind: String = "lead_lag_ack",
    val originalTraceId: String,
    val ackTraceId: String = generateAckTraceId(originalTraceId),
    val senderBotId: String,
    val receiverBotId: String,
    val ackedAtEpochMs: Long,
    val status: AckStatus,
    val error: String? = null,
)

enum class AckStatus {
    ACKED,
    NACK_TIMEOUT,
    NACK_INVALID,
    NACK_REJECTED,
}

private fun generateAckTraceId(original: String): String = "ack-${original.take(12)}-${System.currentTimeMillis() % 10000}"

