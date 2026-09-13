package id.kibot.monitor.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import id.kibot.monitor.data.ControlPlaneSnapshot
import id.kibot.monitor.data.KiBotRepository
import id.kibot.monitor.data.SettingsState
import id.kibot.monitor.data.SettingsStore
import id.kibot.monitor.service.KiBotMonitoringService
import id.kibot.monitor.widget.KiBotWorkScheduler
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers

data class KiBotUiState(
  val settings: SettingsState = SettingsState(),
  val snapshot: ControlPlaneSnapshot? = null,
  val loading: Boolean = true,
  val refreshing: Boolean = false,
  val error: String? = null,
)

class KiBotDashboardViewModel(application: Application) : AndroidViewModel(application) {
  private val settingsStore = SettingsStore.instance()
  private val repository = KiBotRepository(application)
  private val _uiState = MutableStateFlow(KiBotUiState())
  val uiState: StateFlow<KiBotUiState> = _uiState.asStateFlow()

  init {
    viewModelScope.launch {
      settingsStore.state.collectLatest { settings ->
        _uiState.value = _uiState.value.copy(settings = settings)
      }
    }
    viewModelScope.launch(Dispatchers.IO) {
      val cached = repository.loadCachedSnapshot()
      _uiState.value = _uiState.value.copy(snapshot = cached, loading = false)
    }
    refresh(source = "app_start", force = true)
  }

  fun refresh(source: String = "manual", force: Boolean = true) {
    viewModelScope.launch(Dispatchers.IO) {
      _uiState.value = _uiState.value.copy(refreshing = true, error = null)
      try {
        val snapshot = repository.refreshNow(source = source, force = force)
        _uiState.value = _uiState.value.copy(snapshot = snapshot, loading = false, refreshing = false, error = null)
      } catch (exc: Exception) {
        val cached = repository.loadCachedSnapshot()
        _uiState.value = _uiState.value.copy(
          snapshot = cached ?: _uiState.value.snapshot,
          loading = false,
          refreshing = false,
          error = exc.message ?: exc::class.simpleName ?: "Unknown error",
        )
      }
    }
  }

  fun applyBaseUrl(value: String) {
    viewModelScope.launch(Dispatchers.IO) {
      settingsStore.setBaseUrl(value)
      refresh(source = "base_url", force = true)
    }
  }

  fun applyAuthCredentials(username: String, password: String) {
    viewModelScope.launch(Dispatchers.IO) {
      settingsStore.setAuthCredentials(username, password)
      refresh(source = "auth_credentials", force = true)
    }
  }

  fun setMonitoringEnabled(enabled: Boolean) {
    viewModelScope.launch(Dispatchers.IO) {
      settingsStore.setMonitoringEnabled(enabled)
      if (enabled) {
        KiBotWorkScheduler.schedule(getApplication(), _uiState.value.settings.pollIntervalMinutes)
        refresh(source = "monitoring_enabled", force = true)
      } else {
        KiBotWorkScheduler.cancel(getApplication())
        KiBotMonitoringService.stop(getApplication())
      }
    }
  }

  fun setPollInterval(minutes: Int) {
    viewModelScope.launch(Dispatchers.IO) {
      settingsStore.setPollIntervalMinutes(minutes)
      if (_uiState.value.settings.monitoringEnabled) {
        KiBotWorkScheduler.schedule(getApplication(), minutes)
      }
    }
  }
}
