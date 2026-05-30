package id.kibot.monitor.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

@Serializable
data class ControlPlaneDocument(
  @SerialName("generated_at") val generatedAt: String? = null,
  @SerialName("generated_at_wib") val generatedAtWib: String? = null,
  val runtime: JsonElement? = null,
  val portfolio: JsonElement? = null,
  val decision: JsonElement? = null,
  val venues: JsonElement? = null,
  val ai: JsonElement? = null,
  @SerialName("ai_system") val aiSystem: JsonElement? = null,
  val orders: JsonElement? = null,
  val logs: JsonElement? = null,
  val workflow: JsonElement? = null,
  val freshness: JsonElement? = null,
  @SerialName("live_truth") val liveTruth: JsonElement? = null,
  @SerialName("pnl_reconciliation") val pnlReconciliation: JsonElement? = null,
  @SerialName("accounting_truth") val accountingTruth: JsonElement? = null,
  @SerialName("server_truth") val serverTruth: JsonElement? = null,
  @SerialName("system_truth") val systemTruth: JsonElement? = null,
  val brain: JsonElement? = null,
  val system: JsonElement? = null,
  @SerialName("decision_journal") val decisionJournal: JsonElement? = null,
)

data class WorkflowStepSnapshot(
  val name: String,
  val status: String,
  val freshnessSeconds: Double?,
  val reason: String,
)

data class ControlPlaneSnapshot(
  val fetchedAtEpochMs: Long,
  val httpStatus: Int,
  val source: String,
  val rawJson: String,
  val generatedAt: String?,
  val generatedAtWib: String?,
  val runtimeMode: String,
  val runtimeState: String,
  val runtimeFreshnessSeconds: Double?,
  val totalEquityIdr: Double,
  val netPnlTodayIdr: Double,
  val maxDailyLossIdr: Double,
  val riskRemainingIdr: Double,
  val openPositionsCount: Int,
  val currentAction: String,
  val currentReason: String,
  val nextAction: String,
  val lastGatePassed: String,
  val lastGateFailed: String,
  val indodaxStatus: String,
  val indodaxEquityIdr: Double,
  val phantomStatus: String,
  val phantomEquityIdr: Double,
  val aiStatus: String,
  val aiBestAction: String,
  val aiObjective: String,
  val aiReason: String,
  val aiMarketSummary: String,
  val aiRiskStatus: String,
  val aiVenue: String,
  val aiConfidence: Double?,
  val aiActiveComponents: Int,
  val aiLockedComponents: Int,
  val aiOrderPermission: String,
  val aiOverridePermission: String,
  val orderOpenCount: Int,
  val orderPendingCount: Int,
  val orderRejectedCount: Int,
  val orderDustCount: Int,
  val logExceptionCount: Int,
  val logActivityCount: Int,
  val workflowSteps: List<WorkflowStepSnapshot>,
  val freshnessBreakdown: Map<String, Double>,
  val serverOnline: Boolean?,
  val cpuPercent: Double?,
  val diskPercent: Double?,
  val ramPercent: Double?,
  val liveFresh: Boolean?,
  val latestActivityPreview: String?,
  val latestTradePreview: String?,
  val raw: ControlPlaneDocument,
) {
  val stateLabel: String get() = statusLabel(runtimeState)
  val modeLabel: String get() = runtimeMode.ifBlank { "LIVE_ONLY" }
}

data class ParsedControlPlane(
  val rawJson: String,
  val httpStatus: Int,
  val fetchedAtEpochMs: Long,
  val source: String,
  val snapshot: ControlPlaneSnapshot,
)

object ControlPlaneParser {
  private val json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    isLenient = true
    coerceInputValues = true
  }

  fun parse(rawJson: String, httpStatus: Int, fetchedAtEpochMs: Long, source: String): ParsedControlPlane {
    val document = json.decodeFromString(ControlPlaneDocument.serializer(), rawJson)
    val root = json.parseToJsonElement(rawJson).jsonObject
    val snapshot = ControlPlaneSnapshot(
      fetchedAtEpochMs = fetchedAtEpochMs,
      httpStatus = httpStatus,
      source = source,
      rawJson = rawJson,
      generatedAt = document.generatedAt,
      generatedAtWib = document.generatedAtWib,
      runtimeMode = root.stringAt("runtime", "mode") ?: "LIVE_ONLY",
      runtimeState = root.stringAt("runtime", "state") ?: "OK",
      runtimeFreshnessSeconds = root.doubleAt("runtime", "freshness_s") ?: root.doubleAt("freshness", "telemetry_age_s"),
      totalEquityIdr = root.doubleAny(
        listOf("portfolio", "total_equity_idr"),
        listOf("accounting_truth", "current_total_equity_idr"),
        listOf("accounting_truth", "snapshot_total_equity_idr"),
      ) ?: 0.0,
      netPnlTodayIdr = root.doubleAny(
        listOf("portfolio", "combined_pnl_idr"),
        listOf("portfolio", "daily_pnl_idr"),
        listOf("accounting_truth", "daily_pnl_idr"),
        listOf("pnl_reconciliation", "canonical", "daily_pnl_idr"),
      ) ?: 0.0,
      maxDailyLossIdr = root.doubleAny(
        listOf("pnl_reconciliation", "canonical", "max_daily_loss_idr"),
        listOf("accounting_truth", "max_daily_loss_idr"),
      ) ?: 0.0,
      riskRemainingIdr = root.doubleAny(
        listOf("pnl_reconciliation", "canonical", "risk_remaining_idr"),
        listOf("accounting_truth", "max_daily_loss_idr"),
      ) ?: 0.0,
      openPositionsCount = root.elementCountAny(
        listOf("portfolio", "active_positions"),
        listOf("orders", "open_orders"),
      ),
      currentAction = root.stringAny(
        listOf("decision", "current_action"),
        listOf("ai", "best_action"),
        listOf("decision_journal", "latest_decision", "action"),
      ) ?: "WAIT",
      currentReason = root.stringAny(
        listOf("decision", "current_reason"),
        listOf("ai", "reason"),
        listOf("decision_journal", "latest_decision", "reason"),
      ) ?: "",
      nextAction = root.stringAny(
        listOf("decision", "current_action"),
        listOf("ai", "best_action"),
        listOf("decision_journal", "latest_decision", "next_autonomous_action"),
      ) ?: "WAIT",
      lastGatePassed = root.stringAny(listOf("decision", "last_gate_passed"), listOf("decision_journal", "latest_decision", "last_gate_passed")) ?: "",
      lastGateFailed = root.stringAny(listOf("decision", "last_gate_failed"), listOf("decision_journal", "latest_decision", "last_gate_failed")) ?: "",
      indodaxStatus = root.stringAny(
        listOf("accounting_truth", "phantom_treasury", "indodax", "status"),
        listOf("venues", "indodax_real", "status"),
      ) ?: "UNKNOWN",
      indodaxEquityIdr = root.doubleAny(
        listOf("accounting_truth", "indodax_equity_idr"),
        listOf("accounting_truth", "phantom_treasury", "indodax", "equity_idr"),
        listOf("venues", "indodax_real", "equity_idr"),
      ) ?: 0.0,
      phantomStatus = root.stringAny(
        listOf("accounting_truth", "phantom_treasury", "phantom", "status"),
        listOf("venues", "phantom", "status"),
      ) ?: "UNKNOWN",
      phantomEquityIdr = root.doubleAny(
        listOf("accounting_truth", "phantom_equity_idr"),
        listOf("accounting_truth", "phantom_treasury", "phantom", "equity_idr"),
        listOf("venues", "phantom", "equity_idr"),
      ) ?: 0.0,
      aiStatus = root.stringAny(
        listOf("ai_system", "status"),
        listOf("ai", "risk_status"),
        listOf("brain", "status"),
      ) ?: "UNKNOWN",
      aiBestAction = root.stringAny(listOf("ai", "best_action"), listOf("decision", "current_action")) ?: "WAIT",
      aiObjective = root.stringAny(listOf("ai", "objective"), listOf("brain", "posture")) ?: "",
      aiReason = root.stringAny(listOf("ai", "reason"), listOf("decision", "current_reason")) ?: "",
      aiMarketSummary = root.stringAny(listOf("ai", "market_summary"), listOf("ai", "risk_status")) ?: "",
      aiRiskStatus = root.stringAny(listOf("ai", "risk_status"), listOf("brain", "risk")) ?: "",
      aiVenue = root.stringAny(listOf("ai", "venue"), listOf("decision_journal", "latest_decision", "venue")) ?: "",
      aiConfidence = root.doubleAny(listOf("ai", "confidence"), listOf("decision_journal", "latest_decision", "confidence")),
      aiActiveComponents = root.intAny(listOf("ai_system", "active_components"), listOf("ai", "active_components")),
      aiLockedComponents = root.intAny(listOf("ai_system", "locked_or_conditional_components")),
      aiOrderPermission = root.stringAny(listOf("ai_system", "order_permission"), listOf("ai", "order_permission")) ?: "NO",
      aiOverridePermission = root.stringAny(listOf("ai_system", "override_permission"), listOf("ai", "override_permission")) ?: "NO",
      orderOpenCount = root.elementCountAny(listOf("orders", "open_orders")),
      orderPendingCount = root.intAny(listOf("orders", "pending_orders")),
      orderRejectedCount = root.elementCountAny(listOf("orders", "rejected_candidates")),
      orderDustCount = root.elementCountAny(listOf("orders", "dust_positions")),
      logExceptionCount = root.elementCountAny(listOf("logs", "exceptions")),
      logActivityCount = root.elementCountAny(listOf("logs", "operator_activity")),
      workflowSteps = root.arrayAt("workflow", "steps").mapNotNull { step ->
        val item = step.jsonObject
        WorkflowStepSnapshot(
          name = item.stringAt("name") ?: "",
          status = item.stringAt("status") ?: "",
          freshnessSeconds = item.doubleAt("freshness_s"),
          reason = item.stringAt("reason") ?: "",
        )
      },
      freshnessBreakdown = root.objectAt("freshness")?.entries?.associate { (key, value) -> key to (value.asDoubleOrNull() ?: 0.0) } ?: emptyMap(),
      serverOnline = root.booleanAt("system_truth", "batam_server_online"),
      cpuPercent = root.doubleAt("server_truth", "cpu", "percent") ?: root.doubleAt("system", "cpu"),
      diskPercent = root.doubleAt("server_truth", "disk", "percent") ?: root.doubleAt("system", "disk"),
      ramPercent = root.doubleAt("server_truth", "ram", "percent") ?: root.doubleAt("system", "ram"),
      liveFresh = root.booleanAt("live_truth", "fresh"),
      latestActivityPreview = root.previewEntry("logs", "operator_activity"),
      latestTradePreview = root.previewEntry("decision_journal", "latest_trade_event"),
      raw = document,
    )
    return ParsedControlPlane(rawJson, httpStatus, fetchedAtEpochMs, source, snapshot)
  }
}

private fun JsonElement?.objectOrNull(): JsonObject? = this as? JsonObject
private fun JsonElement?.arrayOrNull(): JsonArray? = this as? JsonArray
private fun JsonElement?.stringOrNull(): String? = (this as? JsonPrimitive)?.content?.takeIf { it.isNotBlank() }
private fun JsonElement?.doubleOrNull(): Double? = (this as? JsonPrimitive)?.doubleOrNull ?: this?.jsonPrimitive?.content?.toDoubleOrNull()
private fun JsonElement?.intOrNull(): Int? = (this as? JsonPrimitive)?.content?.toIntOrNull()
private fun JsonElement?.booleanOrNull(): Boolean? = (this as? JsonPrimitive)?.content?.toBooleanStrictOrNull()

private fun JsonObject.objectAt(vararg path: String): JsonObject? = elementAt(*path).objectOrNull()
private fun JsonObject.arrayAt(vararg path: String): List<JsonElement> = elementAt(*path).arrayOrNull()?.toList() ?: emptyList()
private fun JsonObject.stringAt(vararg path: String): String? = elementAt(*path).stringOrNull()
private fun JsonObject.doubleAt(vararg path: String): Double? = elementAt(*path).doubleOrNull()
private fun JsonObject.intAt(vararg path: String): Int? = elementAt(*path).intOrNull()
private fun JsonObject.booleanAt(vararg path: String): Boolean? = elementAt(*path).booleanOrNull()
private fun JsonObject.elementCountAny(vararg paths: List<String>): Int = paths.asSequence().map { elementAt(*it.toTypedArray()) }.map { when (it) { is JsonObject -> it.size; is JsonArray -> it.size; else -> 0 } }.firstOrNull { it > 0 } ?: 0
private fun JsonObject.intAny(vararg paths: List<String>): Int = paths.asSequence().mapNotNull { elementAt(*it.toTypedArray()).intOrNull() }.firstOrNull() ?: 0
private fun JsonObject.doubleAny(vararg paths: List<String>): Double? = paths.asSequence().mapNotNull { elementAt(*it.toTypedArray()).doubleOrNull() }.firstOrNull()
private fun JsonObject.stringAny(vararg paths: List<String>): String? = paths.asSequence().mapNotNull { elementAt(*it.toTypedArray()).stringOrNull() }.firstOrNull()
private fun JsonObject.previewEntry(vararg path: String): String? {
  val element = elementAt(*path)
  val array = element.arrayOrNull() ?: return element.objectOrNull()?.toPreview()
  return array.firstOrNull()?.let {
    it.objectOrNull()?.toPreview()
  }
}
private fun JsonObject.elementAt(vararg path: String): JsonElement? {
  var current: JsonElement? = this
  for (key in path) {
    current = current?.objectOrNull()?.get(key)
  }
  return current
}
private fun JsonObject.toPreview(): String? {
  val keys = listOf("status", "action", "ticker", "reason", "logic", "source", "event_type", "decision_state")
  return keys.mapNotNull { this[it]?.stringOrNull() }.joinToString(" · ").takeIf { it.isNotBlank() }
}
private fun JsonElement?.asDoubleOrNull(): Double? = when (this) {
  null, JsonNull -> null
  else -> this.doubleOrNull()
}
