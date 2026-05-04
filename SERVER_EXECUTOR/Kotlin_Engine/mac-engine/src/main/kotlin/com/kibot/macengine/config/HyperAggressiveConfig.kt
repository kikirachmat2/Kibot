package com.kibot.macengine.config

data class HyperAggressiveConfig(
    val targetDailyPct: Double = 25.0,
    val sexyWindowMs: Long = 60_000L,
    val sexyMinPriceDeltaPct: Double = 1.5,
    val sexyMinVolumeAnomalyMultiplier: Double = 2.5,
    val sexyMinTradeActivityScore: Double = 0.72,
    val superSexyWindowMs: Long = 2_000L,
    val superSexyMinPriceDeltaPct: Double = 4.0,
    val superSexyMinVolumeAnomalyMultiplier: Double = 10.0,
    val vShapeDumpWindowMs: Long = 5_000L,
    val vShapeMinDumpPct: Double = 5.0,
    val vShapeBounceConfirmMs: Long = 6_000L,
    val vShapeBounceVolumeAnomalyMultiplier: Double = 4.0,
    val wallSmasherWindowMs: Long = 6_000L,
    val wallSmasherVolumeAnomalyMultiplier: Double = 4.5,
    val wallSmasherMinSpreadCompressionPct: Double = 25.0,
    val volumeBaselineWindowMs: Long = 60_000L,
    val stagnantWindowMs: Long = 180_000L,
    val stagnantMaxMovePct: Double = 0.5,
    val trailingStopPct: Double = 1.5,
    val trailingArmMinGainPct: Double = 0.8,
    val microPulseKeepMs: Long = 190_000L,
    val microPulseMaxSamplesPerPair: Int = 260,
    val microPulseMaxPairs: Int = 1400,
    val allInLiquidationMaxPnlPct: Double = 1.0,
)

