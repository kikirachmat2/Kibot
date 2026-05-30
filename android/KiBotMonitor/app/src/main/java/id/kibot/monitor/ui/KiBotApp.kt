package id.kibot.monitor.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Analytics
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.ShowChart
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.ViewList
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import id.kibot.monitor.data.KiBotRepository
import id.kibot.monitor.data.SettingsStore
import kotlinx.coroutines.launch

private data class NavItem(val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KiBotApp() {
  val scope = rememberCoroutineScope()
  val snackbar = remember { SnackbarHostState() }
  var selectedTab by remember { mutableIntStateOf(0) }
  val settings = remember { SettingsStore.instance() }
  val context = LocalContext.current
  val baseUrl by settings.baseUrl.collectAsState(initial = "https://dashboard.168.110.201.228.sslip.io")
  val monitoringEnabled by settings.monitoringEnabled.collectAsState(initial = false)
  val repository = remember(baseUrl) { KiBotRepository(context) }
  var snapshot by remember { androidx.compose.runtime.mutableStateOf<id.kibot.monitor.data.KiBotSnapshot?>(null) }

  LaunchedEffect(baseUrl, selectedTab) {
    snapshot = repository.loadSnapshot()
  }

  Scaffold(
    topBar = { TopAppBar(title = { Text("KiBot Monitor") }) },
    snackbarHost = { SnackbarHost(hostState = snackbar) },
    bottomBar = {
      NavigationBar {
        val items = listOf(
          NavItem("Ringkasan", Icons.Outlined.Analytics),
          NavItem("Venue", Icons.Outlined.Storage),
          NavItem("AI", Icons.Outlined.Notifications),
          NavItem("Order", Icons.Outlined.ViewList),
          NavItem("Log", Icons.Outlined.ShowChart),
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
    }
  ) { padding ->
    Column(
      modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
      verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
      val payload = snapshot?.payload
      Card(colors = CardDefaults.cardColors()) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
          Text("Autonomous LIVE_ONLY runtime", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
          Text("Can trade when deterministic gates pass. No profit guarantee.", style = MaterialTheme.typography.bodyMedium)
          Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            AssistChip(onClick = {}, label = { Text("Mode: ${payload?.runtime?.mode ?: "LIVE_ONLY"}") })
            AssistChip(onClick = {}, label = { Text("Fresh: ${payload?.runtime?.freshness_s ?: 0.0}s") })
            AssistChip(onClick = {}, label = { Text(if (monitoringEnabled) "Monitoring aktif" else "Monitoring mati") })
          }
        }
      }
      Card {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
          Text("Total Equity", fontWeight = FontWeight.SemiBold)
          Text("Rp ${payload?.portfolio?.total_equity_idr?.toLong() ?: 0L}", style = MaterialTheme.typography.headlineMedium)
          Text("Net PnL Today: Rp ${payload?.portfolio?.net_pnl_today_idr?.toLong() ?: 0L}")
          Text("Risk Remaining: Rp ${payload?.portfolio?.risk_remaining_idr?.toLong() ?: 0L}")
        }
      }
      when (selectedTab) {
        1 -> VenuePane(payload)
        2 -> AiPane(payload)
        3 -> OrdersPane(payload)
        4 -> LogsPane(payload)
        5 -> SettingsPane(baseUrl = baseUrl)
        else -> OverviewPane(payload)
      }
    }
  }
}

@Composable private fun OverviewPane(payload: id.kibot.monitor.data.ControlPlanePayload?) {
  Card { Column(Modifier.fillMaxWidth().padding(16.dp)) { Text("Ringkasan"); Spacer(Modifier.size(8.dp)); Text("Action: ${payload?.decision?.current_action ?: "WAIT"}"); Text("Reason: ${payload?.decision?.current_reason ?: "—"}") } }
}

@Composable private fun VenuePane(payload: id.kibot.monitor.data.ControlPlanePayload?) {
  Card { Column(Modifier.fillMaxWidth().padding(16.dp)) { Text("Venue"); Text("Indodax: ${payload?.venues?.indodax?.status ?: "—"}"); Text("Phantom: ${payload?.venues?.phantom?.status ?: "—"}") } }
}

@Composable private fun AiPane(payload: id.kibot.monitor.data.ControlPlanePayload?) {
  Card { Column(Modifier.fillMaxWidth().padding(16.dp)) { Text("AI"); Text("Status: ${payload?.aiSystem?.status ?: "—"}"); Text("Can place order: NO"); Text("Can override gate: NO") } }
}

@Composable private fun OrdersPane(payload: id.kibot.monitor.data.ControlPlanePayload?) {
  Card { Column(Modifier.fillMaxWidth().padding(16.dp)) { Text("Order"); Text("Open: ${payload?.orders?.open_orders?.size ?: 0}"); Text("Closed: ${payload?.orders?.closed_trades?.size ?: 0}"); Text("Dust: ${payload?.orders?.dust_positions?.size ?: 0}") } }
}

@Composable private fun LogsPane(payload: id.kibot.monitor.data.ControlPlanePayload?) {
  Card { Column(Modifier.fillMaxWidth().padding(16.dp)) { Text("Log"); Text("Exceptions: ${payload?.logs?.exceptions?.size ?: 0}"); Text("Legacy debug present: ${payload?.debug?.legacy_debug != null}") } }
}

@Composable private fun SettingsPane(baseUrl: String) {
  Card { Column(Modifier.fillMaxWidth().padding(16.dp)) { Text("Pengaturan"); Text("Base URL: $baseUrl") } }
}
