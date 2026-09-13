package id.kibot.monitor.widget

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import id.kibot.monitor.data.SettingsStore
import id.kibot.monitor.service.KiBotMonitoringService
import id.kibot.monitor.worker.KiBotSyncWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class KiBotActionReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent?) {
    when (intent?.action) {
      ACTION_REFRESH -> launchAsync(context) {
        KiBotWorkScheduler.enqueueImmediate(context, "widget_or_notification")
      }
      ACTION_STOP -> launchAsync(context) {
        SettingsStore.instance().setMonitoringEnabled(false)
        KiBotWorkScheduler.cancel(context)
        KiBotMonitoringService.stop(context)
        KiBotStatusWidgetProvider.updateAll(context)
      }
      else -> Log.i(TAG, "ignored action=${intent?.action}")
    }
  }

  private fun launchAsync(context: Context, block: suspend () -> Unit) {
    val pending = goAsync()
    CoroutineScope(Dispatchers.IO).launch {
      try {
        block()
      } finally {
        pending.finish()
      }
    }
  }

  companion object {
    const val ACTION_REFRESH = "id.kibot.monitor.action.REFRESH_NOW"
    const val ACTION_STOP = "id.kibot.monitor.action.STOP_MONITORING"
    private const val TAG = "KiBotWidget"
  }
}

object KiBotWorkScheduler {
  fun schedule(context: Context, pollIntervalMinutes: Int) {
    val intervalMinutes = pollIntervalMinutes.coerceAtLeast(MIN_INTERVAL_MINUTES)
    val request = androidx.work.PeriodicWorkRequestBuilder<KiBotSyncWorker>(intervalMinutes.toLong(), java.util.concurrent.TimeUnit.MINUTES)
      .setInputData(
        androidx.work.workDataOf(
          KiBotSyncWorker.KEY_FORCE to false,
          KiBotSyncWorker.KEY_SOURCE to "periodic",
        ),
      )
      .build()
    androidx.work.WorkManager.getInstance(context.applicationContext).enqueueUniquePeriodicWork(
      WORK_NAME,
      androidx.work.ExistingPeriodicWorkPolicy.UPDATE,
      request,
    )
  }

  fun enqueueImmediate(context: Context, source: String) {
    val request = androidx.work.OneTimeWorkRequestBuilder<KiBotSyncWorker>()
      .setInputData(
        androidx.work.workDataOf(
          KiBotSyncWorker.KEY_FORCE to true,
          KiBotSyncWorker.KEY_SOURCE to source,
        ),
      )
      .build()
    androidx.work.WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
      REFRESH_WORK_NAME,
      androidx.work.ExistingWorkPolicy.REPLACE,
      request,
    )
  }

  fun cancel(context: Context) {
    val manager = androidx.work.WorkManager.getInstance(context.applicationContext)
    manager.cancelUniqueWork(WORK_NAME)
    manager.cancelUniqueWork(REFRESH_WORK_NAME)
  }

  const val WORK_NAME = "kibot_sync_periodic"
  const val REFRESH_WORK_NAME = "kibot_sync_refresh"
  private const val MIN_INTERVAL_MINUTES = 15
}
