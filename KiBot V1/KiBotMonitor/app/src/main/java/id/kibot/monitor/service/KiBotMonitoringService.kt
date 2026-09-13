package id.kibot.monitor.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import id.kibot.monitor.MainActivity
import id.kibot.monitor.R
import id.kibot.monitor.data.ControlPlaneSnapshot
import id.kibot.monitor.data.SettingsStore
import id.kibot.monitor.data.formatIdr
import id.kibot.monitor.data.formatFreshness
import id.kibot.monitor.data.statusLabel
import id.kibot.monitor.widget.KiBotActionReceiver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking

class KiBotMonitoringService : Service() {
  override fun onBind(intent: Intent?): IBinder? = null

  override fun onCreate() {
    super.onCreate()
    createChannel()
    startForeground(NOTIFICATION_ID, buildNotification("KiBot menunggu sinkronisasi"))
  }

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    when (intent?.action) {
      ACTION_STOP -> {
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
        return START_NOT_STICKY
      }
      ACTION_UPDATE, null -> {
        val title = intent?.getStringExtra(EXTRA_TITLE) ?: "KiBot LIVE_ONLY"
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "KiBot menunggu sinkronisasi"
        val snapshot = intent?.getStringExtra(EXTRA_SNAPSHOT_TEXT)
        startForeground(NOTIFICATION_ID, buildNotification(text, title, snapshot))
      }
    }
    return START_STICKY
  }

  override fun onDestroy() {
    stopForeground(STOP_FOREGROUND_REMOVE)
    super.onDestroy()
  }

  private fun buildNotification(text: String, title: String = "KiBot LIVE_ONLY", snapshotText: String? = null): Notification {
    val openIntent = PendingIntent.getActivity(
      this,
      0,
      Intent(this, MainActivity::class.java),
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val refreshIntent = PendingIntent.getBroadcast(
      this,
      1,
      Intent(this, KiBotActionReceiver::class.java).setAction(KiBotActionReceiver.ACTION_REFRESH),
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val stopIntent = PendingIntent.getBroadcast(
      this,
      2,
      Intent(this, KiBotActionReceiver::class.java).setAction(KiBotActionReceiver.ACTION_STOP),
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    return NotificationCompat.Builder(this, CHANNEL_ID)
      .setSmallIcon(R.mipmap.ic_launcher)
      .setContentTitle(title)
      .setContentText(text)
      .setStyle(NotificationCompat.BigTextStyle().bigText(snapshotText ?: text))
      .setContentIntent(openIntent)
      .setOngoing(true)
      .setOnlyAlertOnce(true)
      .setPriority(NotificationCompat.PRIORITY_LOW)
      .addAction(0, "Open App", openIntent)
      .addAction(0, "Refresh Now", refreshIntent)
      .addAction(0, "Stop Monitoring", stopIntent)
      .build()
  }

  private fun createChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val channel = NotificationChannel(CHANNEL_ID, "KiBot Live Sync", NotificationManager.IMPORTANCE_LOW)
    val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    manager.createNotificationChannel(channel)
  }

  companion object {
    const val CHANNEL_ID = "kibot_monitoring"
    const val NOTIFICATION_ID = 2001
    const val ACTION_UPDATE = "id.kibot.monitor.action.UPDATE_NOTIFICATION"
    const val ACTION_STOP = "id.kibot.monitor.action.STOP_NOTIFICATION"
    const val EXTRA_TITLE = "extra_title"
    const val EXTRA_TEXT = "extra_text"
    const val EXTRA_SNAPSHOT_TEXT = "extra_snapshot_text"
    private const val TAG = "KiBotService"

    fun update(context: Context, snapshot: ControlPlaneSnapshot) {
      val settings = runBlocking(Dispatchers.IO) { SettingsStore.instance().snapshot() }
      if (!settings.monitoringEnabled) {
        Log.i(TAG, "update skipped monitoring_disabled=true")
        return
      }
      val text = buildText(snapshot)
      val title = "KiBot LIVE_ONLY"
      val intent = Intent(context, KiBotMonitoringService::class.java).apply {
        action = ACTION_UPDATE
        putExtra(EXTRA_TITLE, title)
        putExtra(EXTRA_TEXT, text)
        putExtra(EXTRA_SNAPSHOT_TEXT, buildBigText(snapshot))
      }
      ContextCompat.startForegroundService(context, intent)
    }

    fun stop(context: Context) {
      context.stopService(Intent(context, KiBotMonitoringService::class.java).setAction(ACTION_STOP))
    }

    private fun buildText(snapshot: ControlPlaneSnapshot): String {
      val freshness = formatFreshness(snapshot.runtimeFreshnessSeconds)
      val pnl = formatIdr(snapshot.netPnlTodayIdr)
      val state = statusLabel(snapshot.runtimeState)
      return "$state · PnL $pnl · ${freshness.removePrefix("fresh ")}"
    }

    private fun buildBigText(snapshot: ControlPlaneSnapshot): String {
      return buildString {
        appendLine("Mode: ${snapshot.modeLabel}")
        appendLine("State: ${snapshot.stateLabel}")
        appendLine("Equity: ${formatIdr(snapshot.totalEquityIdr)}")
        appendLine("Net PnL: ${formatIdr(snapshot.netPnlTodayIdr)}")
        appendLine("Risk Remaining: ${formatIdr(snapshot.riskRemainingIdr)}")
        appendLine("Indodax: ${snapshot.indodaxStatus} · ${formatIdr(snapshot.indodaxEquityIdr)}")
        appendLine("Phantom: ${snapshot.phantomStatus} · ${formatIdr(snapshot.phantomEquityIdr)}")
        appendLine("Action: ${snapshot.currentAction}")
        appendLine("Reason: ${snapshot.currentReason.ifBlank { "—" }}")
      }
    }
  }
}
