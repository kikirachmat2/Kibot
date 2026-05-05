package com.kibot.core

import com.kibot.shared.models.MarketQuote

class ChartAnalyzer {
    enum class PreferredOrderType {
        AVOID,
        MARKET,
        LIMIT_MID,
        LIMIT_PASSIVE,
    }

    data class ChartHistoryAssessment(
        val blocked: Boolean,
        val blockedReason: String? = null,
        val rangeOpportunityScore: Double = 0.0,
        val progressiveScore: Double = 0.0,
        val deadChartScore: Double = 0.0,
        val shouldAvoidEntry: Boolean = false,
        val entryScore: Double = 0.0,
        val exhaustionRiskScore: Double = 0.0,
        val rotationUrgencyScore: Double = 0.0,
        val netEntryScore: Double = 0.0,
        val preferredOrderType: PreferredOrderType = PreferredOrderType.LIMIT_MID,
    )

    fun analyzeQuoteSnapshot(quote: MarketQuote): ChartHistoryAssessment {
        val shouldAvoid = quote.spreadPct > 1.8 || quote.estimatedSlippagePct > 1.8
        val preferred = when {
            shouldAvoid -> PreferredOrderType.AVOID
            quote.spreadPct <= 0.25 -> PreferredOrderType.MARKET
            quote.spreadPct <= 0.75 -> PreferredOrderType.LIMIT_MID
            else -> PreferredOrderType.LIMIT_PASSIVE
        }
        val entryScore = (
            quote.trendQualityScore * 0.28 +
                quote.holdabilityScore * 0.18 +
                quote.recentTradeActivityScore * 0.16 +
                quote.orderBookStabilityScore * 0.14 +
                quote.fillQualityScore * 0.12 +
                (1.0 - quote.estimatedSlippagePct.coerceAtMost(5.0) / 5.0) * 0.12
            ).coerceIn(0.0, 1.0)
        return ChartHistoryAssessment(
            blocked = shouldAvoid,
            blockedReason = if (shouldAvoid) "chart_guard_avoid_entry" else null,
            rangeOpportunityScore = quote.volatilityQualityScore.coerceIn(0.0, 1.0),
            progressiveScore = quote.trendQualityScore.coerceIn(0.0, 1.0),
            deadChartScore = (1.0 - quote.recentTradeActivityScore.coerceIn(0.0, 1.0)).coerceIn(0.0, 1.0),
            shouldAvoidEntry = shouldAvoid,
            entryScore = entryScore,
            exhaustionRiskScore = (quote.rsi14 / 100.0).coerceIn(0.0, 1.0),
            rotationUrgencyScore = (quote.vwapDistancePct / 10.0).coerceIn(0.0, 1.0),
            netEntryScore = entryScore,
            preferredOrderType = preferred,
        )
    }

    fun assessHistoryGuard(
        candleCount: Int,
        activeCandleCount: Int,
        distinctCloseBuckets: Int,
        rangePct: Double,
        lastClose: Double,
        dominantCloseShare: Double,
        directionFlipRate: Double,
        higherHighRatio: Double,
        higherLowRatio: Double,
        closingProgressRatio: Double,
        netProgressPct: Double,
        minCandles: Int,
        minActiveCandles: Int,
        minDistinctCloseBuckets: Int,
        cheapNominalMaxPrice: Double,
        cheapNominalMinDistinctCloses: Int,
        minRangePct: Double,
    ): ChartHistoryAssessment {
        val blocked = candleCount < minCandles || activeCandleCount < minActiveCandles
        val preferred = when {
            lastClose <= cheapNominalMaxPrice && distinctCloseBuckets >= cheapNominalMinDistinctCloses -> PreferredOrderType.MARKET
            rangePct >= minRangePct && higherHighRatio >= 0.55 && higherLowRatio >= 0.55 -> PreferredOrderType.LIMIT_MID
            else -> PreferredOrderType.AVOID
        }
        val rangeOpportunityScore = (rangePct / (minRangePct.coerceAtLeast(0.0001))).coerceIn(0.0, 1.0)
        val progressiveScore = ((higherHighRatio + higherLowRatio + closingProgressRatio) / 3.0).coerceIn(0.0, 1.0)
        val deadChartScore = (1.0 - dominantCloseShare + directionFlipRate).coerceIn(0.0, 1.0)
        val entryScore = ((rangeOpportunityScore + progressiveScore + (netProgressPct / 10.0).coerceIn(0.0, 1.0)) / 3.0).coerceIn(0.0, 1.0)
        return ChartHistoryAssessment(
            blocked = blocked,
            blockedReason = if (blocked) "history_guard_blocked" else null,
            rangeOpportunityScore = rangeOpportunityScore,
            progressiveScore = progressiveScore,
            deadChartScore = deadChartScore,
            shouldAvoidEntry = blocked || preferred == PreferredOrderType.AVOID,
            entryScore = entryScore,
            exhaustionRiskScore = dominantCloseShare.coerceIn(0.0, 1.0),
            rotationUrgencyScore = directionFlipRate.coerceIn(0.0, 1.0),
            netEntryScore = entryScore,
            preferredOrderType = preferred,
        )
    }
}
