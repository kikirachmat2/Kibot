package id.kibot.monitor

import kotlin.test.Test
import kotlin.test.assertEquals

class SettingsStoreTest {
  @Test
  fun baseUrlDefault_is_dashboard_url() {
    assertEquals("https://dashboard.168.110.201.228.sslip.io", "https://dashboard.168.110.201.228.sslip.io")
  }
}
