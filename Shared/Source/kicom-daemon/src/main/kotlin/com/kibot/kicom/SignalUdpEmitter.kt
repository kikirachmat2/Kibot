package com.kibot.kicom

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import org.slf4j.LoggerFactory
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.UUID

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import java.util.Base64

class SignalUdpEmitter(
    private val targetHost: String = "127.0.0.1",
    private val targetPort: Int = 9998
) {
    private val logger = LoggerFactory.getLogger(SignalUdpEmitter::class.java)
    private val socket = DatagramSocket()
    private val address = InetAddress.getByName(targetHost)
    private val json = Json { encodeDefaults = true }
    private val signingKey = System.getenv("KIBOT_SIGNAL_KEY") ?: "SOVEREIGN_DEFAULT_SIGNAL_SECRET"

    private fun generateSignature(payload: String): String {
        val hmacSha256 = Mac.getInstance("HmacSHA256")
        val secretKey = SecretKeySpec(signingKey.toByteArray(), "HmacSHA256")
        hmacSha256.init(secretKey)
        val hash = hmacSha256.doFinal(payload.toByteArray())
        return Base64.getEncoder().encodeToString(hash)
    }

    fun emit(momentum: MomentumAnalyzer.PairMomentum, indodaxPair: String) {
        val now = System.currentTimeMillis()
        val traceId = "LL-${UUID.randomUUID().toString().take(8).uppercase()}"

        val payloadMap = mutableMapOf<String, JsonElement>(
            "kind" to JsonPrimitive("lead_lag_breakout"),
            "msgType" to JsonPrimitive("DETECTOR_HIT"),
            "traceId" to JsonPrimitive(traceId),
            "senderBotId" to JsonPrimitive("kicom-daemon-v8"),
            "pairId" to JsonPrimitive(indodaxPair),
            "trend" to JsonPrimitive(if (momentum.priceChangePct > 0) "UP" else "DOWN"),
            "detectedAtEpochMs" to JsonPrimitive(now),
            "sentAtEpochMs" to JsonPrimitive(now),
            "expiresAtEpochMs" to JsonPrimitive(now + 30000), // 30s TTL for paranoid reconstruction
            "confidence" to JsonPrimitive(0.95),
            "conviction" to JsonPrimitive(momentum.convictionScore),
            "shortTermReturnPct" to JsonPrimitive(momentum.priceChangePct),
            "forceRotation" to JsonPrimitive(true)
        )

        // Generate signature over the payload content
        val rawJson = json.encodeToString(JsonObject(payloadMap))
        val signature = generateSignature(rawJson)
        
        // Add signature to final payload
        payloadMap["signature"] = JsonPrimitive(signature)
        val finalJsonStr = json.encodeToString(JsonObject(payloadMap))
        
        val bytes = finalJsonStr.toByteArray()
        val packet = DatagramPacket(bytes, bytes.size, address, targetPort)

        try {
            socket.soTimeout = 200 // 200ms for ACK
            socket.send(packet)
            
            // Wait for ACK
            val ackBuffer = ByteArray(256)
            val ackPacket = DatagramPacket(ackBuffer, ackBuffer.size)
            try {
                socket.receive(ackPacket)
                val ackResponse = String(ackPacket.data, 0, ackPacket.length, Charsets.UTF_8)
                if (ackResponse.contains(traceId)) {
                    logger.info("EMITTED [TRUSTED_ACK] signal for $indodaxPair trace=$traceId")
                } else {
                    logger.warn("EMITTED [INVALID_ACK] expected $traceId but got $ackResponse")
                }
            } catch (te: java.net.SocketTimeoutException) {
                logger.warn("EMITTED [NO_ACK] signal for $indodaxPair trace=$traceId - manager might be offline or unauthorized")
            }

            logger.info("EMITTED lead-lag signal for $indodaxPair (CDC: ${momentum.symbol}) change=${String.format("%.2f", momentum.priceChangePct)}% conviction=${String.format("%.2f", momentum.convictionScore)} trace=$traceId")
        } catch (e: Exception) {
            logger.error("Failed to send UDP signal: ${e.message}")
        }
    }

    fun close() {
        socket.close()
    }
}
