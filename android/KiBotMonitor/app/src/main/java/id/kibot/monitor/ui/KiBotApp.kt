package id.kibot.monitor.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Analytics
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.ListAlt
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.TrendingUp
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material.icons.outlined.Widgets
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import id.kibot.monitor.data.ControlPlaneSnapshot
import id.kibot.monitor.data.formatFreshness
import id.kibot.monitor.data.formatIdr
import id.kibot.monitor.data.formatShortNumber
import id.kibot.monitor.data.statusLabel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private data class NavItem(val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KiBotApp(viewModel: KiBotDashboardViewModel = viewModel()) {
  val uiState by viewModel.uiState.collectAsState()
  val snackbarHostState = remember { SnackbarHostState() }
  var selectedTab by rememberSaveable { mutableIntStateOf(0) }

  LaunchedEffect(uiState.error) {
    uiState.error?.let { snackbarHostState.showSnackbar(it) }
  }

  Scaffold(
    topBar = {
      CenterAlignedTopAppBar(
        title = {
          Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("KiBot", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(
              uiState.snapshot?.let { "${it.modeLabel} · ${formatFreshness(it.runtimeFreshnessSeconds)}" } ?: "Command center",
              style = MaterialTheme.typography.labelMedium,
            )
          }
        },
        actions = {
          IconButton(onClick = { viewModel.refresh(source = "manual", force = true) }) {
            Icon(Icons.Outlined.Refresh, contentDescription = "Refresh now")
          }
        },
        colors = TopAppBarDefaults.centerAlignedTopAppBarColors(),
      )
    },
    snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
    bottomBar = {
      NavigationBar {
        val items = listOf(
          NavItem("Ringkasan", Icons.Outlined.Analytics),
          NavItem("Venue", Icons.Outlined.Storage),
          NavItem("AI", Icons.Outlined.AutoAwesome),
          NavItem("Order", Icons.Outlined.ListAlt),
          NavItem("Log", Icons.Outlined.History),
          NavItem("Pengaturan", Icons.Outlined.Settings),
        )
        items.forEachIndexed { index, item ->
          NavigationBarItem(
            selected = selectedTab == index,
            onClick = { selectedTab = index },
            icon = { Icon(item.icon, contentDescription = item.label) },
            label = { Text(item.label) },
          )
        }
      }
    },
  ) { padding ->
    Box(
      modifier = Modifier
        .fillMaxSize()
        .padding(padding),
    ) {
      when (selectedTab) {
        1 -> VenueScreen(uiState.snapshot)
        2 -> AiScreen(uiState.snapshot)
        3 -> OrderScreen(uiState.snapshot)
        4 -> LogScreen(uiState.snapshot)
        5 -> SettingsScreen(
          settings = uiState.settings,
          snapshot = uiState.snapshot,
          isLoading = uiState.loading || uiState.refreshing,
          onApplyBaseUrl = viewModel::applyBaseUrl,
          onApplyAuthCredentials = viewModel::applyAuthCredentials,
          onMonitoringToggle = viewModel::setMonitoringEnabled,
          onPollIntervalChange = viewModel::setPollInterval,
          onTestConnection = { viewModel.refresh(source = "test_connection", force = true) },
          onRefresh = { viewModel.refresh(source = "settings", force = true) },
        )
        else -> OverviewScreen(uiState.snapshot, uiState.settings.monitoringEnabled, uiState.loading, uiState.refreshing, uiState.error, onRefresh = { viewModel.refresh(source = "overview", force = true) })
      }
      AnimatedVisibility(visible = uiState.loading || uiState.refreshing) {
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
      }
    }
  }
}

@Composable
private fun OverviewScreen(
  snapshot: ControlPlaneSnapshot?,
  monitoringEnabled: Boolean,
  loading: Boolean,
  refreshing: Boolean,
  error: String?,
  onRefresh: () -> Unit,
) {
  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    verticalArrangement = Arrangement.spacedBy(16.dp),
    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
  ) {
    item {
      HeroCard(snapshot = snapshot, monitoringEnabled = monitoringEnabled, loading = loading, refreshing = refreshing, error = error, onRefresh = onRefresh)
    }
    item { KPIGrid(snapshot) }
    item { DecisionCard(snapshot) }
    item { VenueCompactCard(snapshot) }
  }
}

@Composable
private fun VenueScreen(snapshot: ControlPlaneSnapshot?) {
  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    verticalArrangement = Arrangement.spacedBy(16.dp),
    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
  ) {
    item {
      SectionHeader("Venue", "Indodax dan Phantom tampil dari control-plane real.")
    }
    item {
      DetailVenueCard(
        title = "Indodax",
        status = snapshot?.indodaxStatus ?: "UNKNOWN",
        equity = snapshot?.indodaxEquityIdr,
        summary = "Status pipeline Indodax",
        chips = listOf("Wallet", "Risk gate", "Reconciled"),
      )
    }
    item {
      DetailVenueCard(
        title = "Phantom / Solana",
        status = snapshot?.phantomStatus ?: "UNKNOWN",
        equity = snapshot?.phantomEquityIdr,
        summary = "Status treasury Phantom",
        chips = listOf("Wallet", "Treasury", "RPC"),
      )
    }
  }
}

@Composable
private fun AiScreen(snapshot: ControlPlaneSnapshot?) {
  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    verticalArrangement = Arrangement.spacedBy(16.dp),
    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
  ) {
    item { SectionHeader("AI", "Advisory only. Tidak ada tombol trading.") }
    item {
      DetailInfoCard(
        title = "AI system",
        rows = listOf(
          "Status" to (snapshot?.aiStatus ?: "UNKNOWN"),
          "Best action" to (snapshot?.aiBestAction ?: "WAIT"),
          "Objective" to (snapshot?.aiObjective ?: "—"),
          "Risk status" to (snapshot?.aiRiskStatus ?: "—"),
          "Venue" to (snapshot?.aiVenue ?: "—"),
          "Confidence" to (snapshot?.aiConfidence?.let { formatShortNumber(it) } ?: "—"),
        ),
        chips = listOf(
          "Can place order: NO",
          "Can override gate: NO",
          "Active components: ${snapshot?.aiActiveComponents ?: 0}",
          "Locked/conditional: ${snapshot?.aiLockedComponents ?: 0}",
        ),
      )
    }
    item {
      DetailInfoCard(
        title = "Reasoning",
        rows = listOf(
          "Market summary" to (snapshot?.aiMarketSummary ?: "—"),
          "Reason" to (snapshot?.aiReason ?: "—"),
          "Current action" to (snapshot?.currentAction ?: "WAIT"),
          "Next action" to (snapshot?.nextAction ?: "WAIT"),
        ),
        chips = listOf(snapshot?.aiOrderPermission ?: "NO", snapshot?.aiOverridePermission ?: "NO"),
      )
    }
  }
}

@Composable
private fun OrderScreen(snapshot: ControlPlaneSnapshot?) {
  val hasOrders = (snapshot?.orderOpenCount ?: 0) > 0 || (snapshot?.orderPendingCount ?: 0) > 0 || (snapshot?.orderRejectedCount ?: 0) > 0
  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    verticalArrangement = Arrangement.spacedBy(16.dp),
    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
  ) {
    item { SectionHeader("Order", "Open positions, pending orders, dan quarantine.") }
    item {
      KPIGrid(snapshot)
    }
    item {
      if (hasOrders) {
        DetailInfoCard(
          title = "Order queue",
          rows = listOf(
            "Open orders" to "${snapshot?.orderOpenCount ?: 0}",
            "Pending orders" to "${snapshot?.orderPendingCount ?: 0}",
            "Rejected candidates" to "${snapshot?.orderRejectedCount ?: 0}",
            "Dust positions" to "${snapshot?.orderDustCount ?: 0}",
          ),
          chips = listOf("Queue active", "Review required"),
        )
      } else {
        EmptyStateCard(
          title = "Tidak ada posisi aktif",
          body = "Sistem sedang menunggu setup yang lolos gate.",
          icon = Icons.Outlined.Widgets,
        )
      }
    }
  }
}

@Composable
private fun LogScreen(snapshot: ControlPlaneSnapshot?) {
  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    verticalArrangement = Arrangement.spacedBy(16.dp),
    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
  ) {
    item { SectionHeader("Log", "Activity, exception, dan technical trace.") }
    item {
      DetailInfoCard(
        title = "Summary",
        rows = listOf(
          "Operator activity" to "${snapshot?.logActivityCount ?: 0}",
          "Exceptions" to "${snapshot?.logExceptionCount ?: 0}",
          "Server online" to (snapshot?.serverOnline?.toString() ?: "—"),
          "CPU / RAM / Disk" to listOf(snapshot?.cpuPercent, snapshot?.ramPercent, snapshot?.diskPercent).joinToString(" / ") { it?.let(::formatShortNumber) ?: "—" },
        ),
        chips = listOf(
          snapshot?.latestActivityPreview ?: "No activity",
          snapshot?.latestTradePreview ?: "No trade event",
        ),
      )
    }
    item {
      DetailInfoCard(
        title = "Freshness",
        rows = snapshot?.freshnessBreakdown?.entries?.sortedBy { it.key }?.map { (key, value) -> key.replace('_', ' ') to "${value.toInt()}s" } ?: listOf("freshness" to "—"),
        chips = snapshot?.workflowSteps?.take(4)?.map { "${it.name}: ${it.status}" } ?: listOf("No workflow data"),
      )
    }
  }
}

@Composable
private fun SettingsScreen(
  settings: id.kibot.monitor.data.SettingsState,
  snapshot: ControlPlaneSnapshot?,
  isLoading: Boolean,
  onApplyBaseUrl: (String) -> Unit,
  onApplyAuthCredentials: (String, String) -> Unit,
  onMonitoringToggle: (Boolean) -> Unit,
  onPollIntervalChange: (Int) -> Unit,
  onTestConnection: () -> Unit,
  onRefresh: () -> Unit,
) {
  var baseUrlDraft by rememberSaveable(settings.baseUrl) { mutableStateOf(settings.baseUrl) }
  var usernameDraft by rememberSaveable(settings.authUsername) { mutableStateOf(settings.authUsername) }
  var passwordDraft by rememberSaveable(settings.authPassword) { mutableStateOf(settings.authPassword) }
  var intervalDraft by rememberSaveable(settings.pollIntervalMinutes) { mutableStateOf(settings.pollIntervalMinutes.toString()) }

  LaunchedEffect(settings.baseUrl) { baseUrlDraft = settings.baseUrl }
  LaunchedEffect(settings.authUsername) { usernameDraft = settings.authUsername }
  LaunchedEffect(settings.authPassword) { passwordDraft = settings.authPassword }
  LaunchedEffect(settings.pollIntervalMinutes) { intervalDraft = settings.pollIntervalMinutes.toString() }

  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    verticalArrangement = Arrangement.spacedBy(16.dp),
    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
  ) {
    item { SectionHeader("Pengaturan", "Endpoint server SG2, autentikasi, dan status sinkronisasi.") }
    item {
      ElevatedCard {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
          Text("Endpoint Server (SG2 Monitor)", fontWeight = FontWeight.SemiBold)
          Text(
            "Masukkan URL monitor SG2 (contoh: http://213.35.118.26:8788). Jangan gunakan IP Batam lama.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
          )
          OutlinedTextField(
            value = baseUrlDraft,
            onValueChange = { baseUrlDraft = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Base URL") },
            placeholder = { Text("http://213.35.118.26:8788") },
            singleLine = true,
          )
          if (baseUrlDraft.isBlank()) {
            Text(
              "⚠️ Base URL belum diisi. Masukkan URL server agar app dapat memantau data.",
              style = MaterialTheme.typography.bodySmall,
              color = MaterialTheme.colorScheme.error,
            )
          }
          Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = { onApplyBaseUrl(baseUrlDraft) }) { Text("Simpan URL") }
            TextButton(onClick = onTestConnection, enabled = !isLoading && baseUrlDraft.isNotBlank()) { Text("Test connection") }
          }
        }
      }
    }
    item {
      ElevatedCard {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
          Text("Autentikasi (Basic Auth)", fontWeight = FontWeight.SemiBold)
          Text(
            "Kredensial jika endpoint Nginx SG2 dilindungi autentikasi password.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
          )
          OutlinedTextField(
            value = usernameDraft,
            onValueChange = { usernameDraft = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Username") },
            singleLine = true,
          )
          OutlinedTextField(
            value = passwordDraft,
            onValueChange = { passwordDraft = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Password") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
          )
          Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = { onApplyAuthCredentials(usernameDraft, passwordDraft) }) {
              Text("Simpan Kredensial")
            }
          }
        }
      }
    }
    item {
      ElevatedCard {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
          Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column {
              Text("Monitoring aktif", fontWeight = FontWeight.SemiBold)
              Text("Menjaga service, sync, dan widget berjalan.")
            }
            Switch(checked = settings.monitoringEnabled, onCheckedChange = onMonitoringToggle)
          }
          OutlinedTextField(
            value = intervalDraft,
            onValueChange = { intervalDraft = it.filter { char -> char.isDigit() } },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Interval sync (menit)") },
            singleLine = true,
          )
          Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = { onPollIntervalChange(intervalDraft.toIntOrNull() ?: settings.pollIntervalMinutes) }) { Text("Simpan interval") }
            TextButton(onClick = onRefresh, enabled = !isLoading) { Text("Sinkron sekarang") }
          }
        }
      }
    }
    item {
      DetailInfoCard(
        title = "Snapshot debug",
        rows = listOf(
          "Last fetch status" to settings.lastFetchStatus,
          "Last HTTP status" to (settings.lastHttpStatus?.toString() ?: "—"),
          "Last error" to (settings.lastError ?: "—"),
          "Last updated" to (settings.lastUpdatedEpochMs?.let { formatEpoch(it) } ?: "—"),
          "Freshness" to (settings.lastFreshnessSeconds?.let { formatFreshness(it) } ?: "—"),
          "Widget" to "KiBot Status 5x2",
          "No profit guarantee" to "Aktif",
        ),
        chips = listOf(
          "Package: id.kibot.monitor",
          "Widget refresh: enabled",
          "Foreground notification: enabled",
        ),
      )
    }
    item {
      EmptyStateCard(
        title = "Add widget manually",
        body = "Long press home screen → Widgets → KiBot → KiBot Status 5x2 → Add.",
        icon = Icons.Outlined.Widgets,
      )
    }
    item {
      snapshot?.let {
        DetailInfoCard(
          title = "Control plane quick view",
          rows = listOf(
            "Action" to it.currentAction,
            "Reason" to (it.currentReason.ifBlank { "—" }),
            "Total equity" to formatIdr(it.totalEquityIdr),
            "Net PnL today" to formatIdr(it.netPnlTodayIdr),
            "Risk remaining" to formatIdr(it.riskRemainingIdr),
          ),
          chips = listOf(statusLabel(it.runtimeState), formatFreshness(it.runtimeFreshnessSeconds), it.modeLabel),
        )
      }
    }
  }
}

@Composable
private fun HeroCard(
  snapshot: ControlPlaneSnapshot?,
  monitoringEnabled: Boolean,
  loading: Boolean,
  refreshing: Boolean,
  error: String?,
  onRefresh: () -> Unit,
) {
  ElevatedCard {
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
      Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Column {
          Text("KiBot LIVE_ONLY", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
          Text(snapshot?.generatedAtWib ?: snapshot?.generatedAt ?: "Menunggu data control-plane")
        }
        IconButton(onClick = onRefresh) { Icon(Icons.Outlined.Refresh, contentDescription = "Refresh now") }
      }
      Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        StatusChip(statusLabel(snapshot?.runtimeState ?: "WAIT"))
        StatusChip(snapshot?.runtimeMode ?: "LIVE_ONLY")
        StatusChip(if (monitoringEnabled) "Monitoring aktif" else "Monitoring mati")
        StatusChip(snapshot?.serverOnline?.let { if (it) "Server online" else "Server offline" } ?: "Server ?")
      }
      if (snapshot != null) {
        Text("Equity ${formatIdr(snapshot.totalEquityIdr)}", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("Action: ${snapshot.currentAction}")
      } else {
        Text("Belum ada snapshot cache.", style = MaterialTheme.typography.bodyLarge)
      }
      val progress = snapshot?.let {
        val cap = it.maxDailyLossIdr.takeIf { cap -> cap > 0.0 } ?: 1.0
        (1.0 - (it.riskRemainingIdr / cap)).coerceIn(0.0, 1.0).toFloat()
      } ?: 0f
      LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
      if (error != null) {
        AssistChip(onClick = {}, label = { Text(error) }, colors = AssistChipDefaults.assistChipColors(containerColor = MaterialTheme.colorScheme.errorContainer))
      }
      AnimatedVisibility(visible = loading || refreshing) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
          CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
          Text("Sinkronisasi data...")
        }
      }
    }
  }
}

@Composable
private fun KPIGrid(snapshot: ControlPlaneSnapshot?) {
  Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
      MetricCard("Total Equity", formatIdr(snapshot?.totalEquityIdr), Icons.Outlined.TrendingUp, Modifier.weight(1f))
      MetricCard("Net PnL Hari Ini", formatIdr(snapshot?.netPnlTodayIdr), Icons.Outlined.Analytics, Modifier.weight(1f))
    }
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
      MetricCard("Risk Remaining", formatIdr(snapshot?.riskRemainingIdr), Icons.Outlined.WarningAmber, Modifier.weight(1f))
      MetricCard("Open Positions", snapshot?.openPositionsCount?.toString() ?: "0", Icons.Outlined.Storage, Modifier.weight(1f))
    }
  }
}

@Composable
private fun DecisionCard(snapshot: ControlPlaneSnapshot?) {
  DetailInfoCard(
    title = "Keputusan saat ini",
    rows = listOf(
      "Aksi sekarang" to (snapshot?.currentAction ?: "WAIT"),
      "Alasan" to (snapshot?.currentReason ?: "—"),
      "Next autonomous action" to (snapshot?.nextAction ?: "WAIT"),
      "Last gate passed" to (snapshot?.lastGatePassed ?: "—"),
      "Last gate failed" to (snapshot?.lastGateFailed ?: "—"),
    ),
    chips = listOf(snapshot?.stateLabel ?: "WAIT", snapshot?.modeLabel ?: "LIVE_ONLY"),
  )
}

@Composable
private fun VenueCompactCard(snapshot: ControlPlaneSnapshot?) {
  DetailInfoCard(
    title = "Venue cepat",
    rows = listOf(
      "Indodax" to "${snapshot?.indodaxStatus ?: "UNKNOWN"} · ${formatIdr(snapshot?.indodaxEquityIdr)}",
      "Phantom" to "${snapshot?.phantomStatus ?: "UNKNOWN"} · ${formatIdr(snapshot?.phantomEquityIdr)}",
    ),
    chips = listOf(
      "Indodax ${statusLabel(snapshot?.indodaxStatus)}",
      "Phantom ${statusLabel(snapshot?.phantomStatus)}",
    ),
  )
}

@Composable
private fun DetailVenueCard(title: String, status: String, equity: Double?, summary: String, chips: List<String>) {
  DetailInfoCard(
    title = title,
    rows = listOf(
      "Status" to statusLabel(status),
      "Equity" to formatIdr(equity),
      "Summary" to summary,
    ),
    chips = chips,
  )
}

@Composable
private fun DetailInfoCard(title: String, rows: List<Pair<String, String>>, chips: List<String>) {
  Card(colors = CardDefaults.cardColors()) {
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
      Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
      rows.forEach { (label, value) ->
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
          Text(label, modifier = Modifier.weight(0.45f))
          Text(value, modifier = Modifier.weight(0.55f), fontWeight = FontWeight.SemiBold)
        }
      }
      if (chips.isNotEmpty()) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
          chips.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
              row.forEach {
                StatusChip(it, modifier = Modifier.weight(1f))
              }
              if (row.size == 1) Spacer(modifier = Modifier.weight(1f))
            }
          }
        }
      }
    }
  }
}

@Composable
private fun EmptyStateCard(title: String, body: String, icon: androidx.compose.ui.graphics.vector.ImageVector) {
  Card {
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
      Icon(icon, contentDescription = null)
      Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
      Text(body)
    }
  }
}

@Composable
private fun SectionHeader(title: String, body: String) {
  Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
    Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    Text(body)
  }
}

@Composable
private fun MetricCard(title: String, value: String, icon: androidx.compose.ui.graphics.vector.ImageVector, modifier: Modifier = Modifier) {
  ElevatedCard(modifier = modifier.height(120.dp)) {
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.SpaceBetween) {
      Icon(icon, contentDescription = null)
      Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.labelMedium)
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
      }
    }
  }
}

@Composable
private fun StatusChip(text: String, modifier: Modifier = Modifier) {
  AssistChip(
    onClick = {},
    label = { Text(text) },
    modifier = modifier,
    colors = AssistChipDefaults.assistChipColors(
      containerColor = when {
        text.contains("LOCKED", ignoreCase = true) -> MaterialTheme.colorScheme.errorContainer
        text.contains("WARNING", ignoreCase = true) -> MaterialTheme.colorScheme.tertiaryContainer
        text.contains("aktif", ignoreCase = true) || text.contains("OK", ignoreCase = true) -> MaterialTheme.colorScheme.primaryContainer
        else -> MaterialTheme.colorScheme.surfaceVariant
      },
    ),
  )
}

private fun formatEpoch(epochMs: Long): String {
  return SimpleDateFormat("dd MMM HH:mm:ss", Locale("id", "ID")).format(Date(epochMs))
}
