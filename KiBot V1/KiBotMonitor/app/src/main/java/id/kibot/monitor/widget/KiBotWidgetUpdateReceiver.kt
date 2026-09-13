package id.kibot.monitor.widget

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class KiBotWidgetUpdateReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent?) {
    val pending = goAsync()
    CoroutineScope(Dispatchers.IO).launch {
      try {
        KiBotStatusWidgetProvider.updateAll(context)
      } finally {
        pending.finish()
      }
    }
  }
}
