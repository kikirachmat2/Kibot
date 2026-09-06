package id.kibot.monitor.data

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "kibot_monitor")

data class SettingsState(
  val baseUrl: String = SettingsStore.DEFAULT_BASE_URL,
  val authUsername: String = "",
  val authPassword: String = "",
  val monitoringEnabled: Boolean = false,
  val pollIntervalMinutes: Int = SettingsStore.DEFAULT_POLL_INTERVAL_MINUTES,
  val lastFetchStatus: String = "BELUM",
  val lastHttpStatus: Int? = null,
  val lastError: String? = null,
  val lastUpdatedEpochMs: Long? = null,
  val lastFreshnessSeconds: Double? = null,
)

class SettingsStore private constructor(private val context: Context) {
  companion object {
    const val DEFAULT_BASE_URL = ""
    const val DEFAULT_POLL_INTERVAL_MINUTES = 15
    private val KEY_BASE_URL = stringPreferencesKey("base_url")
    private val KEY_AUTH_USERNAME = stringPreferencesKey("auth_username")
    private val KEY_AUTH_PASSWORD = stringPreferencesKey("auth_password")
    private val KEY_MONITORING_ENABLED = booleanPreferencesKey("monitoring_enabled")
    private val KEY_POLL_INTERVAL_MINUTES = intPreferencesKey("poll_interval_minutes")
    private val KEY_LAST_FETCH_STATUS = stringPreferencesKey("last_fetch_status")
    private val KEY_LAST_HTTP_STATUS = intPreferencesKey("last_http_status")
    private val KEY_LAST_ERROR = stringPreferencesKey("last_error")
    private val KEY_LAST_UPDATED_EPOCH_MS = longPreferencesKey("last_updated_epoch_ms")
    private val KEY_LAST_FRESHNESS_SECONDS = stringPreferencesKey("last_freshness_seconds")
    private var appContext: Context? = null

    fun init(context: Context) {
      appContext = context.applicationContext
    }

    fun instance(): SettingsStore = SettingsStore(appContext ?: throw IllegalStateException("SettingsStore not initialized"))
  }

  val state: Flow<SettingsState> = context.dataStore.data.map { it.toState() }
  val baseUrl: Flow<String> = state.map { it.baseUrl }
  val monitoringEnabled: Flow<Boolean> = state.map { it.monitoringEnabled }

  suspend fun snapshot(): SettingsState = context.dataStore.data.first().toState()

  suspend fun setBaseUrl(value: String) {
    context.dataStore.edit { prefs ->
      prefs[KEY_BASE_URL] = value.trim()
    }
  }

  suspend fun setAuthCredentials(username: String, password: String) {
    context.dataStore.edit { prefs ->
      prefs[KEY_AUTH_USERNAME] = username.trim()
      prefs[KEY_AUTH_PASSWORD] = password
    }
  }

  suspend fun setMonitoringEnabled(enabled: Boolean) {
    context.dataStore.edit { prefs ->
      prefs[KEY_MONITORING_ENABLED] = enabled
    }
  }

  suspend fun setPollIntervalMinutes(minutes: Int) {
    context.dataStore.edit { prefs ->
      prefs[KEY_POLL_INTERVAL_MINUTES] = minutes.coerceAtLeast(DEFAULT_POLL_INTERVAL_MINUTES)
    }
  }

  suspend fun updateFetchMetadata(
    status: String,
    httpStatus: Int? = null,
    error: String? = null,
    updatedEpochMs: Long? = null,
    freshnessSeconds: Double? = null,
  ) {
    context.dataStore.edit { prefs ->
      prefs[KEY_LAST_FETCH_STATUS] = status
      if (httpStatus == null) {
        prefs.remove(KEY_LAST_HTTP_STATUS)
      } else {
        prefs[KEY_LAST_HTTP_STATUS] = httpStatus
      }
      if (error.isNullOrBlank()) {
        prefs.remove(KEY_LAST_ERROR)
      } else {
        prefs[KEY_LAST_ERROR] = error
      }
      if (updatedEpochMs == null) {
        prefs.remove(KEY_LAST_UPDATED_EPOCH_MS)
      } else {
        prefs[KEY_LAST_UPDATED_EPOCH_MS] = updatedEpochMs
      }
      if (freshnessSeconds == null) {
        prefs.remove(KEY_LAST_FRESHNESS_SECONDS)
      } else {
        prefs[KEY_LAST_FRESHNESS_SECONDS] = freshnessSeconds.toString()
      }
    }
  }

  private fun Preferences.toState(): SettingsState {
    return SettingsState(
      baseUrl = this[KEY_BASE_URL] ?: DEFAULT_BASE_URL,
      authUsername = this[KEY_AUTH_USERNAME] ?: "",
      authPassword = this[KEY_AUTH_PASSWORD] ?: "",
      monitoringEnabled = this[KEY_MONITORING_ENABLED] ?: false,
      pollIntervalMinutes = this[KEY_POLL_INTERVAL_MINUTES] ?: DEFAULT_POLL_INTERVAL_MINUTES,
      lastFetchStatus = this[KEY_LAST_FETCH_STATUS] ?: "BELUM",
      lastHttpStatus = this[KEY_LAST_HTTP_STATUS],
      lastError = this[KEY_LAST_ERROR],
      lastUpdatedEpochMs = this[KEY_LAST_UPDATED_EPOCH_MS],
      lastFreshnessSeconds = this[KEY_LAST_FRESHNESS_SECONDS]?.toDoubleOrNull(),
    )
  }
}
