package id.kibot.monitor.worker

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import id.kibot.monitor.data.KiBotRepository

class KiBotSyncWorker(
  appContext: Context,
  params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
  override suspend fun doWork(): Result {
    return try {
      KiBotRepository(applicationContext).refreshNow()
      Result.success()
    } catch (exc: Exception) {
      Result.retry()
    }
  }
}
