package id.kibot.monitor.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import id.kibot.monitor.MainActivity
import id.kibot.monitor.R

class KiBotStatusWidgetProvider : AppWidgetProvider() {
  override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
    appWidgetIds.forEach { updateWidget(context, appWidgetManager, it) }
  }

  override fun onEnabled(context: Context) {
    super.onEnabled(context)
    val intent = Intent(context, KiBotWidgetUpdateReceiver::class.java)
    context.sendBroadcast(intent)
  }

  companion object {
    fun updateAll(context: Context) {
      val manager = AppWidgetManager.getInstance(context)
      val component = ComponentName(context, KiBotStatusWidgetProvider::class.java)
      val ids = manager.getAppWidgetIds(component)
      ids.forEach { updateWidget(context, manager, it) }
    }

    fun updateWidget(context: Context, manager: AppWidgetManager, widgetId: Int) {
      val views = RemoteViews(context.packageName, R.layout.widget_status)
      val openIntent = PendingIntent.getActivity(
        context,
        0,
        Intent(context, MainActivity::class.java),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
      )
      views.setOnClickPendingIntent(R.id.widget_root, openIntent)
      views.setTextViewText(R.id.widget_mode, "KiBot LIVE_ONLY")
      views.setTextViewText(R.id.widget_status, "WAIT / OK / LOCKED")
      views.setTextViewText(R.id.widget_equity, "Equity sync")
      views.setTextViewText(R.id.widget_pnl, "PnL sync")
      views.setTextViewText(R.id.widget_risk, "Risk sync")
      views.setTextViewText(R.id.widget_venue, "Indodax · Phantom")
      manager.updateAppWidget(widgetId, views)
    }
  }
}
