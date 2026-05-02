// KiBot Trinity - Enhanced Self-Intelligence with Daily Profit Guarantee
// This extends SelfLearningSystem.kt with critical hardening features

package com.kibot.core

import kotlin.math.*
import java.time.Instant

/**
 * Enhanced Self-Intelligence with Daily Profit Hardening
 * 
 * Critical additions:
 * 1. Volatility regime scaling (ATR-based position sizing)
 * 2. Consecutive loss cascade detection (DEFENSIVE mode)
 * 3. Daily profit floor enforcement
 * 4. Expectancy score calculation
 * 5. Rapid threshold adaptation
 */
class EnhancedSelfLearningSystem(
    private val baseLearner: SelfLearningSystem
) {
    
    // Volatility regime classification
    enum class VolatilityRegime {
        EXTREME,  // ATR > 10%
        HIGH,     // ATR 5-10%
        NORMAL,   // ATR 2-5%
        LOW       // ATR < 2%
    }
    
    // Trading mode classification
    enum class TradingMode {
        NORMAL,
        DEFENSIVE,
        EMERGENCY_STANDBY,
        RECOVERY
    }
    
    data class VolatilitySnapshot(
        val atr20: Double,
        val regime: VolatilityRegime,
        val positionSizeAdjustment: Double,  // Multiplier: 0.3x to 1.5x
        val timestamp: Instant
    )
    
    data class CascadeState(
        val recentTrades: List<TradeOutcome>,
        val consecutiveLosses: Int,
        val isActive: Boolean,
        val mode: TradingMode
    )
    
    data class DailyProfitState(
        val dailyProfit: Double,
        val dailyLossPercent: Double,
        val floorBreached: Boolean,
        val lastUpdated: Instant
    )
    
    data class ExpectancyScore(
        val winRate: Double,
        val avgWin: Double,
        val avgLoss: Double,
        val expectancyPercent: Double,  // (WR * AvgW) - ((1-WR) * AvgL)
        val confidence: Double           // Based on sample size
    )
    
    private val recentTrades = mutableListOf<TradeOutcome>()
    private var volatilitySnapshot: VolatilitySnapshot? = null
    private var cascadeState = CascadeState(emptyList(), 0, false, TradingMode.NORMAL)
    private var dailyProfitState: DailyProfitState? = null
    private var currentExpectancy: ExpectancyScore? = null
    
    // Configuration constants
    companion object {
        const val CONSECUTIVE_LOSS_THRESHOLD = 3      // Losses in last 5 trades
        const val DAILY_LOSS_FLOOR = -5.0             // Stop trading if down >5% today
        const val CASCADE_POSITION_REDUCTION = 0.5    // 50% position reduction
        const val CASCADE_THRESHOLD_INCREASE = 0.20   // +20% entry threshold
        const val MIN_TRADES_FOR_EXPECTANCY = 10      // Need 10+ trades
        const val FAST_THRESHOLD_ADJUSTMENT = 0.15    // 15% adjustment (faster than 0.05%)
        const val MAX_POSITION_ADJUSTMENT = 2.0       // Never exceed 2x position
        const val MIN_POSITION_ADJUSTMENT = 0.2       // Never go below 0.2x
    }
    
    // ════════════════════════════════════════════════════════════════════════════
    // FEATURE 1: Volatility Regime Scaling
    // ════════════════════════════════════════════════════════════════════════════
    
    fun updateVolatilityRegime(btcAtr20: Double) {
        val regime = when {
            btcAtr20 > 10.0 -> VolatilityRegime.EXTREME
            btcAtr20 > 5.0 -> VolatilityRegime.HIGH
            btcAtr20 > 2.0 -> VolatilityRegime.NORMAL
            else -> VolatilityRegime.LOW
        }
        
        val adjustment = when (regime) {
            VolatilityRegime.EXTREME -> 0.3   // Extreme vol: reduce to 30%
            VolatilityRegime.HIGH -> 0.7      // High vol: reduce to 70%
            VolatilityRegime.NORMAL -> 1.0    // Normal: baseline
            VolatilityRegime.LOW -> 1.5       // Low vol: increase to 150%
        }
        
        volatilitySnapshot = VolatilitySnapshot(
            atr20 = btcAtr20,
            regime = regime,
            positionSizeAdjustment = adjustment.coerceIn(MIN_POSITION_ADJUSTMENT, MAX_POSITION_ADJUSTMENT),
            timestamp = Instant.now()
        )
    }
    
    fun getPositionSizeMultiplier(): Double {
        return volatilitySnapshot?.positionSizeAdjustment ?: 1.0
    }
    
    // ════════════════════════════════════════════════════════════════════════════
    // FEATURE 2: Consecutive Loss Cascade Detection
    // ════════════════════════════════════════════════════════════════════════════
    
    fun recordTrade(outcome: TradeOutcome) {
        recentTrades.add(outcome)
        if (recentTrades.size > 20) {
            recentTrades.removeAt(0)  // Keep rolling window
        }
        
        detectLossCascade()
        updateExpectancy()
    }
    
    private fun detectLossCascade() {
        if (recentTrades.size < 5) {
            cascadeState = cascadeState.copy(consecutiveLosses = 0, isActive = false)
            return
        }
        
        val last5 = recentTrades.takeLast(5)
        val losses = last5.count { it.profitPercent < 0 }
        
        val isActive = losses >= CONSECUTIVE_LOSS_THRESHOLD
        val mode = if (isActive) TradingMode.DEFENSIVE else TradingMode.NORMAL
        
        cascadeState = CascadeState(
            recentTrades = recentTrades.toList(),
            consecutiveLosses = losses,
            isActive = isActive,
            mode = mode
        )
    }
    
    fun isCascadeActive(): Boolean = cascadeState.isActive
    
    fun getCascadeMode(): TradingMode = cascadeState.mode
    
    fun getDefensiveAdjustments(): DefensiveAdjustments {
        return if (cascadeState.isActive) {
            DefensiveAdjustments(
                positionSizeReduction = CASCADE_POSITION_REDUCTION,
                entryThresholdIncrease = CASCADE_THRESHOLD_INCREASE,
                exitTrailingStopTightening = 0.10,  // Tighter stops
                maxConsecutiveEntries = 1            // Max 1 entry per cycle
            )
        } else {
            DefensiveAdjustments(1.0, 0.0, 0.0, 999)
        }
    }
    
    data class DefensiveAdjustments(
        val positionSizeReduction: Double,
        val entryThresholdIncrease: Double,
        val exitTrailingStopTightening: Double,
        val maxConsecutiveEntries: Int
    )
    
    // ════════════════════════════════════════════════════════════════════════════
    // FEATURE 3: Daily Profit Floor Enforcement
    // ════════════════════════════════════════════════════════════════════════════
    
    fun updateDailyProfitState(totalCapitalIdr: Double, currentEquityIdr: Double) {
        val dailyProfit = currentEquityIdr - totalCapitalIdr
        val dailyLossPercent = (dailyProfit / totalCapitalIdr * 100.0).coerceAtMost(0.0)
        val floorBreached = dailyLossPercent < DAILY_LOSS_FLOOR
        
        dailyProfitState = DailyProfitState(
            dailyProfit = dailyProfit,
            dailyLossPercent = dailyLossPercent,
            floorBreached = floorBreached,
            lastUpdated = Instant.now()
        )
    }
    
    fun isDailyLossFloorBreached(): Boolean {
        return dailyProfitState?.floorBreached ?: false
    }
    
    fun getDailyProfitState(): DailyProfitState? = dailyProfitState
    
    // ════════════════════════════════════════════════════════════════════════════
    // FEATURE 4: Expectancy Score Calculation
    // ════════════════════════════════════════════════════════════════════════════
    
    private fun updateExpectancy() {
        if (recentTrades.size < MIN_TRADES_FOR_EXPECTANCY) {
            currentExpectancy = null
            return
        }
        
        val sortedTrades = recentTrades.sortedBy { it.timestamp }
        val wins = sortedTrades.filter { it.profitPercent > 0 }
        val losses = sortedTrades.filter { it.profitPercent < 0 }
        
        if (wins.isEmpty() || losses.isEmpty()) {
            currentExpectancy = null
            return
        }
        
        val winRate = wins.size.toDouble() / sortedTrades.size
        val lossRate = 1.0 - winRate
        
        val avgWin = wins.map { it.profitPercent }.average()
        val avgLoss = losses.map { abs(it.profitPercent) }.average()
        
        val expectancy = (winRate * avgWin) - (lossRate * avgLoss)
        val confidence = (sortedTrades.size.toDouble() / (MIN_TRADES_FOR_EXPECTANCY * 3)).coerceIn(0.0, 1.0)
        
        currentExpectancy = ExpectancyScore(
            winRate = winRate,
            avgWin = avgWin,
            avgLoss = avgLoss,
            expectancyPercent = expectancy,
            confidence = confidence
        )
    }
    
    fun getExpectancy(): ExpectancyScore? = currentExpectancy
    
    fun shouldReducePositionByExpectancy(): Boolean {
        val exp = currentExpectancy ?: return false
        return exp.expectancyPercent < 0  // Negative expectancy
    }
    
    fun getExpectancyPositionAdjustment(): Double {
        val exp = currentExpectancy ?: return 1.0
        
        return when {
            exp.expectancyPercent < 0 -> 0.5        // Negative: reduce to 50%
            exp.expectancyPercent in 0.0..0.5 -> 1.0 // Weak: normal
            exp.expectancyPercent > 1.0 -> 1.1       // Strong: slight increase (10%)
            else -> 1.0
        }
    }
    
    // ════════════════════════════════════════════════════════════════════════════
    // FEATURE 5: Rapid Threshold Adaptation
    // ════════════════════════════════════════════════════════════════════════════
    
    fun calculateAdaptiveThresholds(): AdaptiveThresholds {
        val baseMinProfit = 1.2
        val baseMaxHolding = 90
        
        var profitAdjustment = 0.0
        var holdingAdjustment = 0.0
        
        // Fast adaptation based on cascade state
        if (cascadeState.isActive) {
            profitAdjustment += 0.30  // +30% min profit in cascade
            holdingAdjustment -= 20    // -20 min holding time
        }
        
        // Fast adaptation based on expectancy
        currentExpectancy?.let {
            if (it.expectancyPercent < 0) {
                profitAdjustment += 0.25  // +25% min profit if negative exp
            } else if (it.expectancyPercent > 1.0) {
                profitAdjustment -= 0.10  // -10% min profit if strong exp
                holdingAdjustment += 10   // +10 min holding time
            }
        }
        
        // Fast adaptation based on volatility
        volatilitySnapshot?.let {
            when (it.regime) {
                VolatilityRegime.EXTREME -> {
                    profitAdjustment += 0.50  // +50% min profit in extreme vol
                    holdingAdjustment -= 30
                }
                VolatilityRegime.HIGH -> {
                    profitAdjustment += 0.25
                    holdingAdjustment -= 15
                }
                VolatilityRegime.LOW -> {
                    profitAdjustment -= 0.15  // -15% min profit in low vol
                    holdingAdjustment += 10
                }
                else -> {}  // NORMAL: no adjustment
            }
        }
        
        val adaptiveMinProfit = (baseMinProfit + profitAdjustment)
            .coerceIn(0.5, 3.0)  // Keep in [0.5%, 3.0%]
        
        val adaptiveMaxHolding = (baseMaxHolding + holdingAdjustment)
            .coerceIn(30.0, 180.0)  // Keep in [30min, 180min]
        
        return AdaptiveThresholds(adaptiveMinProfit, adaptiveMaxHolding.toInt())
    }
    
    data class AdaptiveThresholds(
        val minProfitPercent: Double,
        val maxHoldingMinutes: Int
    )
    
    // ════════════════════════════════════════════════════════════════════════════
    // SUMMARY & REPORTING
    // ════════════════════════════════════════════════════════════════════════════
    
    fun getSystemStatus(): SystemStatus {
        val thresholds = calculateAdaptiveThresholds()
        
        return SystemStatus(
            volatilityRegime = volatilitySnapshot?.regime ?: VolatilityRegime.NORMAL,
            positionMultiplier = getPositionSizeMultiplier(),
            cascadeActive = cascadeState.isActive,
            consecutiveLosses = cascadeState.consecutiveLosses,
            tradingMode = cascadeState.mode,
            dailyLossFloorBreached = isDailyLossFloorBreached(),
            expectancy = currentExpectancy,
            adaptiveMinProfit = thresholds.minProfitPercent,
            adaptiveMaxHolding = thresholds.maxHoldingMinutes,
            recentTradeCount = recentTrades.size,
            timestamp = Instant.now()
        )
    }
    
    data class SystemStatus(
        val volatilityRegime: VolatilityRegime,
        val positionMultiplier: Double,
        val cascadeActive: Boolean,
        val consecutiveLosses: Int,
        val tradingMode: TradingMode,
        val dailyLossFloorBreached: Boolean,
        val expectancy: ExpectancyScore?,
        val adaptiveMinProfit: Double,
        val adaptiveMaxHolding: Int,
        val recentTradeCount: Int,
        val timestamp: Instant
    )
}

// Data structure for trade outcomes (should already exist)
data class TradeOutcome(
    val pairId: String,
    val profitPercent: Double,
    val timestamp: Instant,
    val entryPrice: Double,
    val exitPrice: Double,
    val quantity: Double,
    val reason: String
)
