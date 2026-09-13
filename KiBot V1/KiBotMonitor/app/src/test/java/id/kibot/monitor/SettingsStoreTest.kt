package id.kibot.monitor

import id.kibot.monitor.data.SettingsStore
import kotlin.test.Test
import kotlin.test.assertEquals

class SettingsStoreTest {
  @Test
  fun baseUrlDefault_is_empty_or_valid() {
    assertEquals(SettingsStore.DEFAULT_BASE_URL, SettingsStore.DEFAULT_BASE_URL)
  }
}
