package id.kibot.monitor.widget

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import id.kibot.monitor.worker.KiBotSyncWorker
import java.util.concurrent.TimeUnit

class BootReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent?) {
    val request = PeriodicWorkRequestBuilder<KiBotSyncWorker>(15, TimeUnit.MINUTES)
      .setInputData(workDataOf("boot" to true))
      .build()
    WorkManager.getInstance(context).enqueueUniquePeriodicWork(
      WORK_NAME,
      ExistingPeriodicWorkPolicy.UPDATE,
      request,
    )
  }

  companion object {
    const val WORK_NAME = "kibot_sync"
  }
}
