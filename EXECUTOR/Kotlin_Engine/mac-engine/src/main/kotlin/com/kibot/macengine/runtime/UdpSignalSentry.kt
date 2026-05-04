package com.kibot.macengine.runtime

import com.kibot.macengine.config.MacRuntimeConfig
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.serialization.json.Json
import org.slf4j.LoggerFactory
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import javax.crypto.Mac
import javax.crypto.spec.SecretKeyFactory
import javax.crypto.spec.SecretKeySpec

internal class UdpSignalSentry(
    private val config: MacRuntimeConfig,
    private val json: Json,
    private val scope: CoroutineScope
) {
    private val logger = LoggerFactory.getLogger(UdpSignalSentry::class.java)
    val signalChannel = Channel<DecodedUdpPacket>(Channel.UNLIMITED)
    
    private var socket: DatagramSocket? = null
    private var running = false

    fun start() {
        if (!config.leadLagUdpEnabled) return
        running = true
        scope.launch(Dispatchers.IO) {
            runListener()
        }
    }

    fun stop() {
        running = false
        socket?.close()
    }

    private suspend fun runListener() {
        logger.info("Starting hardened UDP Signal Sentry on port ${config.leadLagUdpListenPort}...")
        
        try {
            val s = DatagramSocket(config.leadLagUdpListenPort)
            s.receiveBufferSize = 16 * 1024 * 1024 // 16MB buffer
            s.soTimeout = 1000
            socket = s
            
            val buffer = ByteArray(8192)
            val packet = DatagramPacket(buffer, buffer.size)

            while (running) {
                try {
                    s.receive(packet)
                    val data = packet.data.sliceArray(0 until packet.length)
                    processIncomingPacket(data)
                } catch (e: SocketTimeoutException) {
                    // Periodic check for 'running' flag
                } catch (e: Exception) {
                    if (running) logger.warn("UDP receive error: ${e.message}")
                }
            }
        } catch (e: Exception) {
            logger.error("UDP Sentry failed to start: ${e.message}")
        } finally {
            socket?.close()
            logger.info("UDP Signal Sentry stopped.")
        }
    }

    private fun processIncomingPacket(data: ByteArray) {
        // [HARDENING] Magic Header Check (KIBT)
        if (data.size < 4 || data[0] != 'K'.toByte() || data[1] != 'I'.toByte() || data[2] != 'B'.toByte() || data[3] != 'T'.toByte()) {
            // Check if it's legacy JSON
            val content = String(data, Charsets.UTF_8)
            if (content.startsWith("{") && content.endsWith("}")) {
                handleLegacyJson(content)
            } else {
                logger.warn("Received malformed or unsigned packet from ${socket?.localAddress}. Rejecting.")
            }
            return
        }

        // [HARDENING] HMAC Verification
        if (!verifyHmac(data)) {
            logger.error("Intrusion Attempt! Received packet with invalid HMAC signature. Source potential attacker.")
            return
        }

        // Parse Binary V2
        val decoded = decodeBinaryV2(data)
        if (decoded != null) {
            signalChannel.trySend(decoded)
        }
    }

    private fun verifyHmac(data: ByteArray): Boolean {
        val secret = config.leadLagUdpHmacSecret ?: return true // If no secret, skip (not recommended for production)
        if (data.size < 36) return false // 4 magic + 32 hmac
        
        val payloadSize = data.size - 32
        val providedHmac = data.sliceArray(payloadSize until data.size)
        val payload = data.sliceArray(0 until payloadSize)

        return try {
            val hmac = Mac.getInstance("HmacSHA256")
            hmac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
            val calculated = hmac.doFinal(payload)
            calculated.contentEquals(providedHmac)
        } catch (e: Exception) {
            logger.error("HMAC verification error: ${e.message}")
            false
        }
    }

    private fun decodeBinaryV2(data: ByteArray): DecodedUdpPacket? {
        val buffer = ByteBuffer.wrap(data)
        buffer.get() // skip 'K'
        buffer.get() // skip 'I'
        buffer.get() // skip 'B'
        buffer.get() // skip 'T'
        
        val senderIdBytes = ByteArray(12)
        buffer.get(senderIdBytes)
        val senderBotId = String(senderIdBytes, Charsets.UTF_8).trim()
        
        val typeCode = buffer.get()
        val msgType = UdpBinaryMessageType.fromCode(typeCode)
        val sequenceId = buffer.int
        val sentAt = buffer.long
        
        return when (msgType) {
            UdpBinaryMessageType.HEARTBEAT -> {
                val activePair = readFixedString(buffer, 24)
                val flags = buffer.get().toInt()
                DecodedUdpPacket(
                    heartbeat = TrinityHeartbeatPayload(
                        senderBotId = senderBotId,
                        sentAtEpochMs = sentAt,
                        activePair = activePair.takeIf { it.isNotBlank() },
                        safeModeArmed = flags and 0x02 != 0
                    ),
                    senderBotId = senderBotId,
                    sequenceId = sequenceId,
                    binary = true
                )
            }
            UdpBinaryMessageType.POLYMARKET_SENTIMENT -> {
                val pairId = readFixedString(buffer, 24)
                val sentiment = buffer.float.toDouble()
                val vol = buffer.double
                val biasCode = buffer.get().toInt()
                val bias = when(biasCode) {
                    1 -> "BULLISH"
                    2 -> "BEARISH"
                    else -> "NEUTRAL"
                }
                DecodedUdpPacket(
                    sentiment = PolymarketSentimentPayload(
                        pairId = pairId,
                        sentimentScore = sentiment,
                        bias = bias,
                        volume24h = vol,
                        sentAtEpochMs = sentAt
                    ),
                    senderBotId = senderBotId,
                    sequenceId = sequenceId,
                    binary = true
                )
            }
            UdpBinaryMessageType.DETECTOR_HIT, UdpBinaryMessageType.INSTANT_BUY_ANOMALY -> {
                // DETECTOR_HIT/ANOMALY binary layout (Legacy-compatible but with V2 header)
                val detectedAt = buffer.long
                val expiresAt = buffer.long
                val traceHash = buffer.int
                val pairId = readFixedString(buffer, 24)
                val confidence = buffer.float.toDouble()
                val expectedNet = buffer.float.toDouble()
                val stReturn = buffer.float.toDouble()
                val activity = buffer.float.toDouble()
                val flags = buffer.get().toInt()
                
                DecodedUdpPacket(
                    leadLag = LeadLagCalloutPayload(
                        msgType = msgType.wireMsgType,
                        traceId = "udp-$traceHash",
                        senderBotId = senderBotId,
                        pairId = pairId,
                        detectedAtEpochMs = detectedAt,
                        confidence = confidence,
                        expectedNetPct = expectedNet,
                        shortTermReturnPct = stReturn,
                        mediumTermReturnPct = 0.0,
                        tradeActivityScore = activity,
                        forceRotation = flags and 0x01 != 0,
                        sentAtEpochMs = sentAt,
                        expiresAtEpochMs = expiresAt
                    ),
                    senderBotId = senderBotId,
                    sequenceId = sequenceId,
                    binary = true,
                    dedupKey = "$senderBotId:${msgType.wireMsgType}:$pairId:$traceHash"
                )
            }
            else -> null
        }
    }

    private fun handleLegacyJson(content: String) {
        // [REDACTED] Legacy support for old scanners if needed, but we prefer V2
        // For now, we skip it to encourage migration to hardened protocol
        logger.info("Received legacy JSON packet. Migration to V2 binary suggested.")
    }

    private fun readFixedString(buffer: ByteBuffer, length: Int): String {
        val bytes = ByteArray(length)
        buffer.get(bytes)
        return String(bytes, Charsets.UTF_8).trim()
    }
}
