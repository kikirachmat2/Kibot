package com.kibot.macengine.runtime

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.datetime.Clock
import java.time.Duration
import kotlin.math.max

class ExchangeCircuitBreaker(
    private val maxFailures: Int = 5,
    private val cooldownMs: Long = 60_000L, // 60s
    private val failureWindowMs: Long = 5 * 60 * 1000L, // 5min window
) {
    private val recentFailures = mutableListOf<Long>()
    private val stateMutex = Mutex()
    private var lastTrippedAt: Long = 0L
    private var isTripped = false

    suspend fun executeSafely(operation: suspend () -> Boolean): CircuitBreakerResult {
return stateMutex.withLock {
            when {
                isTripped && (Clock.System.now().toEpochMilliseconds() - lastTrippedAt) < cooldownMs -> {
                    CircuitBreakerResult.Tripped(cooldownMs = cooldownMs, cooldownUntilMs = lastTrippedAt + cooldownMs)
                }
                else -> {
                    val success = operation()
                    if (!success) {
                        val nowMs = Clock.System.now().toEpochMilliseconds()
                        recentFailures.removeAll { it < (nowMs - failureWindowMs) }
                        recentFailures.add(nowMs)
                        if (recentFailures.size >= maxFailures) {
                            trip()
                            CircuitBreakerResult.Tripped(nowMs = nowMs, cooldownMs = cooldownMs)
                        } else {
                            CircuitBreakerResult.Success
                        }
                    } else {
                        CircuitBreakerResult.Success
                    }
                }
            }
        }
    }

    private fun trip() {
        isTripped = true
        lastTrippedAt = Clock.System.now().toEpochMilliseconds()
        recentFailures.clear()
    }

    suspend fun reset() {
        stateMutex.withLock {
            isTripped = false
            lastTrippedAt = 0L
            recentFailures.clear()
        }
    }

    suspend fun state(): CircuitBreakerState = stateMutex.withLock {
        CircuitBreakerState(
            isTripped = isTripped,
            failureCount = recentFailures.size,
            cooldownUntilMs = if (isTripped) lastTrippedAt + cooldownMs else null,
            trippedAtMs = if (isTripped) lastTrippedAt else null,
        )
    }
}

sealed interface CircuitBreakerResult {
    object Success : CircuitBreakerResult
    data class Tripped(
        val nowMs: Long = Clock.System.now().toEpochMilliseconds(),
        val cooldownMs: Long,
        val cooldownUntilMs: Long = nowMs + cooldownMs,
    ) : CircuitBreakerResult
}

data class CircuitBreakerState(
    val isTripped: Boolean,
    val failureCount: Int,
    val cooldownUntilMs: Long?,
    val trippedAtMs: Long?,
)
