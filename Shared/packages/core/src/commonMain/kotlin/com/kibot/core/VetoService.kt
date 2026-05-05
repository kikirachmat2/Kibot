package com.kibot.core

import com.kibot.shared.models.MarketQuote
import com.kibot.shared.models.PairScore

interface VetoService {
    fun shouldVetoEntry(
        candidate: PairScore,
        quote: MarketQuote,
        leadLagSignal: LeadLagSelectionSignal?,
        priceBandAllowed: Boolean,
        softAuditOnly: Boolean = false,
        aiConsensus: Double? = null,
    ): Boolean
}
