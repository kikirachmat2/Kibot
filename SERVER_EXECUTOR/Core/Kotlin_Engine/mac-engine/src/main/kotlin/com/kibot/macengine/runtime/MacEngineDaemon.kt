package com.kibot.macengine.runtime

import com.kibot.core.*
import com.kibot.macengine.config.ExchangeKind
import com.kibot.macengine.config.MacRuntimeConfig
import com.kibot.shared.models.*
import kotlinx.coroutines.*
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.slf4j.LoggerFactory
import java.util.UUID

class MacEngineDaemon(
    private val config: MacRuntimeConfig,
    private val controlPlane: ControlPlaneGateway,
    private val exchange: ExchangeGateway,
    private val clock: Clock = Clock.System,
) {
    private val logger = LoggerFactory.getLogger(MacEngineDaemon::class.java)
    private val reconciliationService = ReconciliationService()
    private val json = Json { ignoreUnknownKeys = true }

    @Serializable
    data class BatamExecutionPayload(
        val exchange: String,      // INDODAX | POLYMARKET
        val pair: String,
        val side: String,          // BUY | SELL
        val amount: Double,
        val price: Double? = null,
        val slippage: Double = 0.01,
        val type: String = "MARKET",
        val marketId: String? = null
    )

    suspend fun start() {
        println("🚀 MacEngineDaemon: REACTIVE Slave Mode Active")
        controlPlane.reportHeartbeat(config.exchangeKind, "ALIVE")

        coroutineScope {
            launch {
                while (isActive) {
                    try {
                        controlPlane.reportHeartbeat(config.exchangeKind, "ALIVE")
                        delay(15_000)
                    } catch (e: Exception) {
                        logger.error("Heartbeat failed", e)
                        delay(5_000)
                    }
                }
            }

            launch {
                while (isActive) {
                    try {
                        processBatamCommands()
                        delay(1_000)
                    } catch (e: Exception) {
                        logger.error("Command polling error", e)
                        delay(5_000)
                    }
                }
            }
        }
    }

    private suspend fun processBatamCommands() {
        val botId = config.controlPlane.botId
        val deviceId = config.device.deviceId
        
        val pendingCommands = controlPlane.fetchPendingCommands(botId, deviceId)
        if (pendingCommands.isNotEmpty()) {
            pendingCommands.forEach { envelope ->
                try {
                    val result = executeBatamCommand(envelope)
                    if (result != null) {
                        controlPlane.markCommandExecuted(envelope.id)
                        println("✅ Command ${envelope.id} Executed: Order ${result.orderId}")
                    }
                } catch (e: Exception) {
                    val errorMsg = e.message ?: "Unknown Execution Error"
                    println("❌ Command ${envelope.id} Failed: $errorMsg")
                    controlPlane.markCommandFailed(envelope.id, errorMsg)
                    controlPlane.appendAuditLog(botId, "EXECUTION_ERROR", "Command ${envelope.id} failed: $errorMsg")
                }
            }
        }
    }

    private suspend fun executeBatamCommand(envelope: CommandEnvelope): OrderSnapshot? {
        val payload = runCatching { 
            json.decodeFromString<BatamExecutionPayload>(envelope.payload) 
        }.getOrElse { 
            throw Exception("Invalid Payload Format")
        }

        println("⚒️ Executing ${payload.side} on ${payload.exchange} for ${payload.pair}")

        // 1. Build ExecutionPlan (Proyeksi ke format Gateway)
        val plan = ExecutionPlan(
            pairId = PairId(payload.pair),
            side = if (payload.side.uppercase() == "BUY") OrderSide.BUY else OrderSide.SELL,
            type = if (payload.type.uppercase() == "LIMIT") OrderType.LIMIT else OrderType.MARKET,
            quantity = payload.amount,
            price = payload.price ?: 0.0,
            maxSlippagePct = payload.slippage,
            // Tambahkan metadata untuk Polymarket jika perlu
            metadata = if (payload.marketId != null) mapOf("marketId" to payload.marketId) else emptyMap()
        )

        // 2. Generate Unique Client Order ID (Idempotency)
        // Kita gunakan ID perintah dari Batam sebagai basis ClientOrderId agar tidak double buy
        val clientOrderId = ClientOrderId("batam-${envelope.id}")

        // 3. Execution
        return exchange.placeOrder(plan, clientOrderId)
    }
}
