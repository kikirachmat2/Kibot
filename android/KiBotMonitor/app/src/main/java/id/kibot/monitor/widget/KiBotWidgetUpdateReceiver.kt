package id.kibot.monitor.widget

import android.appwidget.AppWidgetManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class KiBotWidgetUpdateReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent?) {
    val manager = AppWidgetManager.getInstance(context)
    val component = android.content.ComponentName(context, KiBotStatusWidgetProvider::class.java)
    val ids = manager.getAppWidgetIds(component)
    ids.forEach { KiBotStatusWidgetProvider.updateWidget(context, manager, it) }
  }
}
