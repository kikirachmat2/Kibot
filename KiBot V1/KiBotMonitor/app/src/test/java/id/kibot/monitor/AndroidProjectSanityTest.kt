package id.kibot.monitor

import id.kibot.monitor.data.ControlPlaneParser
import id.kibot.monitor.data.SettingsStore
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class AndroidProjectSanityTest {
  @Test fun default_base_url_exists() {
    assertEquals(SettingsStore.DEFAULT_BASE_URL, SettingsStore.DEFAULT_BASE_URL)
  }

  @Test fun model_defaults() {
    val rawJson = """
      {
        "runtime": {"mode": "LIVE_ONLY", "state": "OK"},
        "portfolio": {"total_equity_idr": 200000.0, "net_pnl_today_idr": 0.0}
      }
    """.trimIndent()
    val parsed = ControlPlaneParser.parse(
      rawJson = rawJson,
      httpStatus = 200,
      fetchedAtEpochMs = System.currentTimeMillis(),
      source = "sanity_test"
    )
    assertEquals("LIVE_ONLY", parsed.snapshot.runtimeMode)
    assertEquals(200000.0, parsed.snapshot.totalEquityIdr)
  }

  @Test fun core_classes_exist() {
    listOf(
      "id.kibot.monitor.MainActivity",
      "id.kibot.monitor.worker.KiBotSyncWorker",
      "id.kibot.monitor.service.KiBotMonitoringService",
      "id.kibot.monitor.widget.KiBotStatusWidgetProvider",
    ).forEach { className ->
      assertNotNull(Class.forName(className))
    }
  }
}
