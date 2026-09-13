package id.kibot.monitor.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import java.io.File

@Serializable
data class CachedControlPlaneEnvelope(
  val fetchedAtEpochMs: Long,
  val httpStatus: Int,
  val source: String,
  val rawJson: String,
)

class KiBotSnapshotStore(context: Context) {
  private val appContext = context.applicationContext
  private val cacheFile = File(appContext.filesDir, CACHE_FILE_NAME)
  private val json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
  }

  suspend fun save(snapshot: ParsedControlPlane) {
    withContext(Dispatchers.IO) {
      cacheFile.writeText(
        json.encodeToString(
          CachedControlPlaneEnvelope.serializer(),
          CachedControlPlaneEnvelope(
            fetchedAtEpochMs = snapshot.fetchedAtEpochMs,
            httpStatus = snapshot.httpStatus,
            source = snapshot.source,
            rawJson = snapshot.rawJson,
          ),
        ),
      )
    }
  }

  suspend fun load(): ControlPlaneSnapshot? {
    return withContext(Dispatchers.IO) {
      if (!cacheFile.exists()) {
        return@withContext null
      }
      val envelope = runCatching {
        json.decodeFromString(CachedControlPlaneEnvelope.serializer(), cacheFile.readText())
      }.getOrNull() ?: return@withContext null
      runCatching {
        ControlPlaneParser.parse(
          rawJson = envelope.rawJson,
          httpStatus = envelope.httpStatus,
          fetchedAtEpochMs = envelope.fetchedAtEpochMs,
          source = envelope.source,
        ).snapshot
      }.getOrNull()
    }
  }

  companion object {
    private const val CACHE_FILE_NAME = "kibot_control_plane_cache.json"
  }
}
