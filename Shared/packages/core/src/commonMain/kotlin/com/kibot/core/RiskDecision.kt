package com.kibot.core

import com.kibot.shared.models.ProfitProtectionStatus
import com.kibot.shared.models.RiskLadderLevel

data class RiskDecision(
    val deploymentMultiplier: Double = 1.0,
    val allowNewEntries: Boolean = true,
    val hardStopTriggered: Boolean = false,
    val riskLadderLevel: RiskLadderLevel = RiskLadderLevel.NORMAL,
    val profitProtectionStatus: ProfitProtectionStatus = ProfitProtectionStatus.INACTIVE,
    val reasons: List<String> = emptyList(),
)
