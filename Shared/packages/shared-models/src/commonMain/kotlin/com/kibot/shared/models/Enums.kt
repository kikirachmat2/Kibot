package com.kibot.shared.models

import kotlinx.serialization.Serializable

@Serializable
enum class DevicePlatform {
    ANDROID,
    MACOS,
}

@Serializable
enum class DeviceRole {
    PRIMARY,
    STANDBY,
}

@Serializable
enum class BotDesiredState {
    OFF,
    ON,
}

@Serializable
enum class BotEffectiveState {
    STOPPED,
    STARTING,
    RUNNING,
    DEGRADED,
    SAFE_MODE,
}

@Serializable
enum class SyncHealth {
    HEALTHY,
    DEGRADED,
    BROKEN,
}

@Serializable
enum class HealthStatus {
    HEALTHY,
    WARNING,
    CRITICAL,
}

@Serializable
enum class LeaseState {
    RELEASED,
    HELD,
    EXPIRED,
    CONFLICT,
}

@Serializable
enum class CommandType {
    START_BOT,
    STOP_BOT,
    REQUEST_TAKEOVER,
    FORCE_SAFE_TAKEOVER,
    RELEASE_CONTROL,
    SYNC_NOW,
    FORCE_STANDBY,
    RESUME_FROM_SAFE_MODE,
    TOGGLE_LIVE_EXECUTION,
}

@Serializable
enum class CommandStatus {
    QUEUED,
    ACKED,
    RUNNING,
    SUCCEEDED,
    FAILED,
    EXPIRED,
}

@Serializable
enum class RiskEventType {
    DAILY_LOSS_LIMIT_REACHED,
    DAILY_REBASE_PENDING,
    POSITION_LIMIT_REACHED,
    MIN_ORDER_NOTIONAL_REJECTED,
    SPREAD_TOO_WIDE,
    SLIPPAGE_TOO_HIGH,
    HEALTH_BLOCK,
    SPLIT_BRAIN_DETECTED,
    RECONCILIATION_REQUIRED,
    CREDENTIALS_LOCKED,
}

@Serializable
enum class OrderSide {
    BUY,
    SELL,
}

@Serializable
enum class OrderType {
    LIMIT,
    MARKET,
}

@Serializable
enum class OrderStatus {
    CREATED,
    SUBMITTING,
    OPEN,
    PARTIALLY_FILLED,
    FILLED,
    CANCEL_REQUESTED,
    CANCELED,
    REJECTED,
    UNKNOWN,
}

@Serializable
enum class PositionState {
    OPENING,
    OPEN,
    CLOSING,
    CLOSED,
}

@Serializable
enum class StrategyMode {
    AUTO_CONSERVATIVE,
    SAFE_MODE,
    SAFE,
    DEFENSIVE,
    GROWTH,
    ATTACK,
}

@Serializable
enum class StrategySignalType {
    NO_TRADE,
    MEAN_REVERSION_ENTRY,
    BREAKOUT_ENTRY,
    SCALE_OUT,
    EXIT,
    HOLD,
}

@Serializable
enum class ReconciliationState {
    CLEAN,
    NEEDS_REVIEW,
    BLOCKED,
}

@Serializable
enum class LogLevel {
    DEBUG,
    INFO,
    WARN,
    ERROR,
}

@Serializable
enum class MarketRegime {
    HEALTHY_UPTREND,
    HEALTHY_SIDEWAYS,
    HIGH_VOLATILITY_UNCLEAR,
    HIGH_VOLATILITY_MOMENTUM,
    BREAKDOWN_PANIC,
}

@Serializable
enum class PairTier {
    TIER_A,
    TIER_B,
    TIER_C,
}

@Serializable
enum class TradingHorizon {
    TACTICAL,
    SWING,
}

@Serializable
enum class BotMode {
    SAFE,
    DEFENSIVE,
    GROWTH,
    ATTACK,
}

@Serializable
enum class EdgeConfidence {
    LOW,
    MEDIUM,
    HIGH,
}

@Serializable
enum class RiskLadderLevel {
    NORMAL,
    WARNING,
    REDUCE_SIZE,
    DEFENSIVE_MODE,
    RESTRICTED_NEW_ENTRIES,
    STOP_NEW_ENTRIES,
    HARD_STOP,
}

@Serializable
enum class ProfitProtectionStatus {
    INACTIVE,
    GUARDING_WEEKLY_PROFIT,
    TRAILING_HIGH_WATERMARK,
    COOLING_AGGRESSION,
}

@Serializable
enum class SetupType {
    NO_TRADE,
    HEALTHY_SHORT_TERM_PULLBACK,
    LIGHT_BREAKOUT_CONTINUATION,
    MICRO_MEAN_REVERSION,
    SWING_TREND_CONTINUATION,
}

@Serializable
enum class DistrustLabel {
    DATA_INTEGRITY_ISSUE,
    SYNC_MISMATCH,
    STALE_LEASE_SUSPECTED,
    AMBIGUOUS_ORDER_STATE,
    FEED_DEGRADED,
    EXECUTION_QUALITY_BAD,
    FAILOVER_NOT_CLEAN,
    EDGE_CONFIDENCE_LOW,
    RISK_LADDER_BLOCKED,
}

@Serializable
enum class HyperTargetKind {
    ALL_IN,
    BARBARIAN,
    LOCAL_AUTONOMY,
    LEAD_LAG,
    WALL_SMASH,
}

@Serializable
enum class CoinClass {
    NAGA,
    MID,
    MICIN,
}
