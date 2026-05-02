package com.kibot.macengine

import com.kibot.aisupport.GeminiSupportClient
import com.kibot.aisupport.GeminiSupportCoordinator
import com.kibot.binance.BinanceCredentials
import com.kibot.binance.BinanceGateway
import com.kibot.controlplane.SupabaseControlPlaneClient
import com.kibot.indodax.IndodaxGateway
import com.kibot.macengine.config.ExchangeKind
import com.kibot.macengine.config.MacRuntimeConfigLoader
import com.kibot.macengine.runtime.MacEngineDaemon
import com.kibot.macengine.runtime.MacCommandDispatcher
import com.kibot.macengine.runtime.PassiveExchangeGateway
import com.kibot.macengine.server.LocalDashboardServer
import com.kibot.macengine.state.MacCommand
import com.kibot.macengine.state.MacStateRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.slf4j.LoggerFactory
import java.nio.file.Paths
import java.util.concurrent.atomic.AtomicReference

fun main(args: Array<String>) {
    val logger = LoggerFactory.getLogger("KiBotMac")
    val config = MacRuntimeConfigLoader.load()
    val repository = MacStateRepository()
    val controlPlane = SupabaseControlPlaneClient(config.controlPlane)
    val exchange = when (config.exchangeKind) {
        ExchangeKind.INDODAX -> config.indodaxCredentials?.let {
            IndodaxGateway(config.indodaxClientConfig, it)
        }
        ExchangeKind.BINANCE_SPOT -> BinanceGateway(
            config.binanceClientConfig,
            config.binanceCredentials ?: BinanceCredentials(apiKey = "", apiSecret = ""),
        )
    } ?: PassiveExchangeGateway()
    val dispatcher = MacCommandDispatcher(
        repository = repository,
        controlPlane = controlPlane,
        config = config,
    )
    // Dashboard comes up before the daemon loop so a slow bootstrap cannot hide the server.
    val server = LocalDashboardServer(
        repository = repository,
        commandDispatcher = dispatcher,
        botId = config.controlPlane.botId,
        host = config.bindHost,
        port = config.port,
        androidReleaseDirectory = Paths.get("").toAbsolutePath().resolve(".dist/android/stable"),
        enableLanAdvertising = config.enableLanAdvertising,
        statePollIntervalMillis = config.dashboardStatePollIntervalMillis,
        logPollIntervalMillis = config.dashboardLogPollIntervalMillis,
    )

    if (args.isNotEmpty()) {
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = config,
            aiSupportCoordinator = config.aiSupportConfig?.let { GeminiSupportCoordinator(it, GeminiSupportClient(it)) },
        )
        handleCliCommand(args.first(), repository, daemon, dispatcher, logger)
        return
    }

    val exceptionHandler = CoroutineExceptionHandler { _, throwable ->
        logger.error("Mac engine daemon coroutine crashed.", throwable)
    }
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default + exceptionHandler)
    val daemonRef = AtomicReference<MacEngineDaemon?>()
    Runtime.getRuntime().addShutdownHook(
        Thread {
            logger.info("Shutting down KiBot mac engine.")
            runBlocking {
                runCatching { daemonRef.get()?.shutdown() }
                    .onFailure { logger.warn("Failed to cancel daemon scopes on shutdown: {}", it.message) }
                runCatching { daemonRef.get()?.flushNonCriticalControlPlaneBufferNow() }
                    .onFailure { logger.warn("Failed to flush buffered non-critical control-plane writes on shutdown: {}", it.message) }
            }
            runCatching { server.stop() }
                .onFailure { logger.warn("Failed to stop dashboard server on shutdown: {}", it.message) }
            scope.cancel()
        },
    )

    server.start()
    scope.launch {
        val daemon = MacEngineDaemon(
            repository = repository,
            controlPlane = controlPlane,
            exchange = exchange,
            config = config,
            aiSupportCoordinator = config.aiSupportConfig?.let { GeminiSupportCoordinator(it, GeminiSupportClient(it)) },
        )
        daemonRef.set(daemon)
        daemon.run()
    }
    runBlocking {
        awaitCancellation()
    }
}

private fun handleCliCommand(
    rawCommand: String,
    repository: MacStateRepository,
    daemon: MacEngineDaemon,
    dispatcher: MacCommandDispatcher,
    logger: org.slf4j.Logger,
) {
    val state = runBlocking {
        when (rawCommand.lowercase()) {
            "status" -> daemon.syncOnce()
            "start" -> {
                dispatcher.dispatch(MacCommand.START_BOT)
                daemon.syncOnce()
            }

            "stop" -> {
                dispatcher.dispatch(MacCommand.STOP_BOT)
                daemon.syncOnce()
            }

            "request-takeover" -> {
                dispatcher.dispatch(MacCommand.REQUEST_TAKEOVER)
                daemon.syncOnce()
            }

            "force-safe-takeover" -> {
                dispatcher.dispatch(MacCommand.FORCE_SAFE_TAKEOVER)
                daemon.syncOnce()
            }

            "release-control" -> {
                dispatcher.dispatch(MacCommand.RELEASE_CONTROL)
                daemon.syncOnce()
            }

            "sync" -> {
                dispatcher.dispatch(MacCommand.SYNC_NOW)
                daemon.syncOnce()
            }

            else -> error("Unknown CLI command: $rawCommand")
        }
        repository.state.value
    }

    logger.info(
        "botRunning={}, effectiveState={}, activeEngine={}, status={}",
        state.isBotRunning,
        state.effectiveState,
        state.activeEngine,
        state.statusMessage,
    )
}
