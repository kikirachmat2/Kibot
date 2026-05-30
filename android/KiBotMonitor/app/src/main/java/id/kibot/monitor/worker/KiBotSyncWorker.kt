package id.kibot.monitor.worker

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import id.kibot.monitor.data.KiBotRepository
import id.kibot.monitor.data.SettingsStore

class KiBotSyncWorker(
  appContext: Context,
  params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
  override suspend fun doWork(): Result {
    val force = inputData.getBoolean(KEY_FORCE, false)
    val source = inputData.getString(KEY_SOURCE) ?: "worker"
    return try {
      val settings = SettingsStore.instance().snapshot()
      if (!force && !settings.monitoringEnabled) {
        Log.i(TAG, "skip source=$source monitoring_disabled=true")
        return Result.success()
      }
      KiBotRepository(applicationContext).refreshNow(source = source, force = force)
      Result.success()
    } catch (exc: Exception) {
      Log.e(TAG, "sync failed source=$source", exc)
      Result.retry()
    }
  }

  companion object {
    const val KEY_FORCE = "force"
    const val KEY_SOURCE = "source"
    private const val TAG = "KiBotWorker"
  }
}
