package id.kibot.monitor

import android.app.Application
import id.kibot.monitor.data.SettingsStore

class KiBotMonitorApp : Application() {
  override fun onCreate() {
    super.onCreate()
    SettingsStore.init(this)
  }
}
