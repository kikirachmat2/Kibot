package id.kibot.monitor.data

import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.util.Locale
import kotlin.math.abs

private val idrFormat = DecimalFormat("#,##0.##", DecimalFormatSymbols(Locale("id", "ID")))
private val integerFormat = DecimalFormat("#,##0", DecimalFormatSymbols(Locale("id", "ID")))

fun formatIdr(value: Double?): String {
  return "Rp ${idrFormat.format(value ?: 0.0)}"
}

fun formatInteger(value: Double?): String {
  return integerFormat.format((value ?: 0.0).toLong())
}

fun formatShortNumber(value: Double?): String {
  val actual = value ?: 0.0
  return when {
    abs(actual) >= 1_000_000_000 -> "${idrFormat.format(actual / 1_000_000_000)}B"
    abs(actual) >= 1_000_000 -> "${idrFormat.format(actual / 1_000_000)}M"
    abs(actual) >= 1_000 -> "${idrFormat.format(actual / 1_000)}K"
    else -> idrFormat.format(actual)
  }
}

fun formatFreshness(seconds: Double?): String {
  val value = seconds ?: 0.0
  return when {
    value < 1 -> "fresh ${value.toString().take(4)}s"
    value < 60 -> "fresh ${value.toInt()}s"
    value < 3600 -> "fresh ${(value / 60).toInt()}m"
    else -> "fresh ${(value / 3600).toInt()}h"
  }
}

fun formatPercent(value: Double?): String {
  return "${idrFormat.format(value ?: 0.0)}%"
}

fun statusLabel(value: String?): String {
  return when ((value ?: "").trim().uppercase(Locale.US)) {
    "OK", "ACTIVE", "READY", "RECONCILED" -> "OK"
    "WAIT", "WAITING", "SCOUTING", "UNKNOWN" -> "WAIT"
    "LOCKED", "DENIED", "BLOCKED", "FAIL", "ERROR" -> "LOCKED"
    "WARNING", "WARN", "STALE" -> "WARNING"
    else -> (value ?: "WAIT").trim().ifEmpty { "WAIT" }
  }
}
