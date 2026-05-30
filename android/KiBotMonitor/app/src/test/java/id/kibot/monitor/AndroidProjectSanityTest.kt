package id.kibot.monitor

import id.kibot.monitor.data.ControlPlanePayload
import id.kibot.monitor.data.SettingsStore
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class AndroidProjectSanityTest {
  @Test fun default_base_url_exists() {
    assertEquals("https://dashboard.168.110.201.228.sslip.io", SettingsStore.DEFAULT_BASE_URL)
  }

  @Test fun model_defaults() {
    val payload = ControlPlanePayload()
    assertEquals("LIVE_ONLY", payload.runtime.mode)
    assertNotNull(payload.portfolio)
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
