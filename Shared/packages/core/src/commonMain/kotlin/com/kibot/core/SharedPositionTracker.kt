package com.kibot.core

import com.kibot.shared.models.PairId
import kotlinx.datetime.Instant
import kotlinx.serialization.Serializable

/**
 * SharedPositionTracker - Passive data store for active positions.
 * No autonomous decision logic here. Just a record of what we hold.
 */
class SharedPositionTracker {
    private val positions = mutableMapOf<String, SharedPosition>()

    fun track(
        pairId: PairId,
        quantity: Double,
        entryPrice: Double,
        openedAt: Instant
    ) {
        positions[pairId.value] = SharedPosition(
            pairId = pairId,
            quantity = quantity,
            entryPrice = entryPrice,
            openedAt = openedAt
        )
    }

    fun untrack(pairId: PairId) {
        positions.remove(pairId.value)
    }

    fun getAll(): List<SharedPosition> = positions.values.toList()
    
    fun get(pairId: PairId): SharedPosition? = positions[pairId.value]
}

@Serializable
data class SharedPosition(
    val pairId: PairId,
    val quantity: Double,
    val entryPrice: Double,
    val openedAt: Instant
)
