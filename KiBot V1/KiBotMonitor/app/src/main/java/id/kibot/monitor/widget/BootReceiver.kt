package id.kibot.monitor.widget

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import id.kibot.monitor.data.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class BootReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent?) {
    val pending = goAsync()
    CoroutineScope(Dispatchers.IO).launch {
      try {
        val settings = SettingsStore.instance().snapshot()
        if (settings.monitoringEnabled) {
          KiBotWorkScheduler.schedule(context.applicationContext, settings.pollIntervalMinutes)
          Log.i(TAG, "boot schedule enabled interval=${settings.pollIntervalMinutes}")
        } else {
          Log.i(TAG, "boot ignored monitoring_disabled=true")
        }
      } finally {
        pending.finish()
      }
    }
  }

  companion object {
    private const val TAG = "KiBotWorker"
  }
}
