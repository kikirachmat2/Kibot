package id.kibot.monitor.data

import android.content.Context
import android.util.Log
import id.kibot.monitor.service.KiBotMonitoringService
import id.kibot.monitor.widget.KiBotStatusWidgetProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class KiBotRepository(context: Context) {
  private val appContext = context.applicationContext
  private val settingsStore = SettingsStore.instance()
  private val snapshotStore = KiBotSnapshotStore(appContext)

  suspend fun loadCachedSnapshot(): ControlPlaneSnapshot? = snapshotStore.load()

  suspend fun refreshNow(source: String, force: Boolean = true): ControlPlaneSnapshot {
    val settings = settingsStore.snapshot()
    if (!force && !settings.monitoringEnabled) {
      Log.i(TAG, "refresh skipped source=$source monitoring_disabled=true")
      return snapshotStore.load() ?: throw IllegalStateException("Monitoring disabled")
    }

    settingsStore.updateFetchMetadata(
      status = "FETCHING",
      updatedEpochMs = System.currentTimeMillis(),
    )

    return withContext(Dispatchers.IO) {
      try {
        val result = KiBotApi(settings.baseUrl).fetchControlPlane(source)
        snapshotStore.save(result.parsed)
        val freshness = result.parsed.snapshot.runtimeFreshnessSeconds
          ?: result.parsed.snapshot.freshnessBreakdown.values.minOrNull()
        settingsStore.updateFetchMetadata(
          status = "SUCCESS",
          httpStatus = result.httpStatus,
          updatedEpochMs = result.parsed.fetchedAtEpochMs,
          freshnessSeconds = freshness,
        )
        dispatchUpdates(result.parsed.snapshot)
        Log.i(
          TAG,
          "refresh ok source=$source state=${result.parsed.snapshot.runtimeState} action=${result.parsed.snapshot.currentAction} equity=${result.parsed.snapshot.totalEquityIdr}",
        )
        result.parsed.snapshot
      } catch (exc: Exception) {
        val cached = snapshotStore.load()
        settingsStore.updateFetchMetadata(
          status = "ERROR",
          error = exc.message ?: exc::class.simpleName ?: "Unknown error",
          updatedEpochMs = System.currentTimeMillis(),
          freshnessSeconds = cached?.runtimeFreshnessSeconds,
        )
        if (cached != null) {
          dispatchUpdates(cached)
        } else {
          KiBotStatusWidgetProvider.updateAll(appContext, null)
        }
        Log.e(TAG, "refresh failed source=$source", exc)
        throw exc
      }
    }
  }

  private fun dispatchUpdates(snapshot: ControlPlaneSnapshot) {
    KiBotStatusWidgetProvider.updateAll(appContext, snapshot)
    KiBotMonitoringService.update(appContext, snapshot)
  }

  companion object {
    private const val TAG = "KiBotRepository"
  }
}
