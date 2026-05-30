package id.kibot.monitor.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.RemoteViews
import id.kibot.monitor.MainActivity
import id.kibot.monitor.R
import id.kibot.monitor.data.ControlPlaneSnapshot
import id.kibot.monitor.data.KiBotRepository
import id.kibot.monitor.data.formatFreshness
import id.kibot.monitor.data.formatIdr
import id.kibot.monitor.data.statusLabel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking

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
    fun updateAll(context: Context, snapshot: ControlPlaneSnapshot? = null) {
      val manager = AppWidgetManager.getInstance(context)
      val component = ComponentName(context, KiBotStatusWidgetProvider::class.java)
      val ids = manager.getAppWidgetIds(component)
      if (ids.isEmpty()) {
        Log.i(TAG, "updateAll skipped no_widgets")
        return
      }
      val current = snapshot ?: runBlocking(Dispatchers.IO) {
        KiBotRepository(context).loadCachedSnapshot()
      }
      ids.forEach { updateWidget(context, manager, it, current) }
      Log.i(TAG, "updateAll widgets=${ids.size} cache=${current != null}")
    }

    fun updateWidget(context: Context, manager: AppWidgetManager, widgetId: Int, snapshot: ControlPlaneSnapshot? = null) {
      val views = RemoteViews(context.packageName, R.layout.widget_kibot_status)
      val openIntent = PendingIntent.getActivity(
        context,
        0,
        Intent(context, MainActivity::class.java),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
      )
      val refreshIntent = PendingIntent.getBroadcast(
        context,
        1,
        Intent(context, KiBotActionReceiver::class.java).setAction(KiBotActionReceiver.ACTION_REFRESH),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
      )
      views.setOnClickPendingIntent(R.id.widget_root, openIntent)
      views.setOnClickPendingIntent(R.id.widget_refresh, refreshIntent)

      if (snapshot == null) {
        renderPlaceholder(views)
      } else {
        renderSnapshot(views, snapshot)
      }

      manager.updateAppWidget(widgetId, views)
    }

    private fun renderPlaceholder(views: RemoteViews) {
      views.setTextViewText(R.id.widget_title, "KiBot")
      views.setTextViewText(R.id.widget_mode, "LIVE_ONLY")
      views.setTextViewText(R.id.widget_freshness, "fresh 0s")
      views.setTextViewText(R.id.widget_status, "MENUNGGU DATA")
      views.setTextViewText(R.id.widget_equity, "Belum ada cache")
      views.setTextViewText(R.id.widget_pnl, "Rp 0")
      views.setTextViewText(R.id.widget_risk, "Rp 0")
      views.setTextViewText(R.id.widget_venue, "Indodax / Phantom")
      views.setTextViewText(R.id.widget_action, "Buka app untuk sinkronisasi awal")
    }

    private fun renderSnapshot(views: RemoteViews, snapshot: ControlPlaneSnapshot) {
      views.setTextViewText(R.id.widget_title, "KiBot")
      views.setTextViewText(R.id.widget_mode, snapshot.modeLabel)
      views.setTextViewText(R.id.widget_freshness, formatFreshness(snapshot.runtimeFreshnessSeconds))
      views.setTextViewText(R.id.widget_status, "${statusLabel(snapshot.runtimeState)} · ${snapshot.currentAction}")
      views.setTextViewText(R.id.widget_equity, formatIdr(snapshot.totalEquityIdr))
      views.setTextViewText(R.id.widget_pnl, formatIdr(snapshot.netPnlTodayIdr))
      views.setTextViewText(R.id.widget_risk, formatIdr(snapshot.riskRemainingIdr))
      views.setTextViewText(
        R.id.widget_venue,
        "Indodax ${statusLabel(snapshot.indodaxStatus)} / Phantom ${statusLabel(snapshot.phantomStatus)}",
      )
      views.setTextViewText(
        R.id.widget_action,
        "Aksi: ${snapshot.currentAction.ifBlank { snapshot.aiBestAction }}",
      )
      Log.i(TAG, "render snapshot state=${snapshot.runtimeState} action=${snapshot.currentAction}")
    }

    private const val TAG = "KiBotWidget"
  }
}
