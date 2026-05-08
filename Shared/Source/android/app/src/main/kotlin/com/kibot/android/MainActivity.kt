package com.kibot.android

import android.app.Application
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.*
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.kibot.android.data.*
import com.kibot.android.ui.*
import com.kibot.android.ui.theme.*
import com.kibot.android.util.PreferencesManager
import com.kibot.android.websocket.KiBotWebSocketClient
import com.kibot.android.http.StatePollingClient
import com.kibot.android.widget.KiBotWidgetHelper
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

// Navigation destinations
sealed class Screen(
    val route: String,
    val title: String,
    val selectedIcon: ImageVector,
    val unselectedIcon: ImageVector
) {
    object Dashboard : Screen("dashboard", "Dashboard", Icons.Filled.Dashboard, Icons.Outlined.Dashboard)
    object Portfolio : Screen("portfolio", "Portfolio", Icons.Filled.PieChart, Icons.Outlined.PieChart)
    object Ledger : Screen("ledger", "History", Icons.Filled.Receipt, Icons.Outlined.Receipt)
    object Settings : Screen("settings", "Settings", Icons.Filled.Settings, Icons.Outlined.Settings)
}

class KiBotViewModel(application: Application) : AndroidViewModel(application) {
    private val preferencesManager = PreferencesManager(application)
    private val initialServerConfig = preferencesManager.getServerConfig()
    
    // Primary: HTTP polling client
    private val pollingClient = com.kibot.android.http.StatePollingClient(
        initialServerConfig.getUrl()
    )
    // Fallback: WebSocket client
    private val wsClient = KiBotWebSocketClient(initialServerConfig.getUrl())
    
    private val _connectionStatus = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    val connectionStatus: StateFlow<ConnectionStatus> = _connectionStatus.asStateFlow()
    private val _botState = MutableStateFlow(BotState())
    val botState: StateFlow<BotState> = _botState.asStateFlow()
    private val _errors = MutableSharedFlow<String>(extraBufferCapacity = 32)
    val errors: SharedFlow<String> = _errors.asSharedFlow()
    
    private val _currentScreen = MutableStateFlow<Screen>(Screen.Dashboard)
    val currentScreen: StateFlow<Screen> = _currentScreen
    private val _serverConfig = MutableStateFlow(initialServerConfig)
    val serverConfig: StateFlow<ServerConfig> = _serverConfig

    init {
        viewModelScope.launch {
            combine(pollingClient.connectionStatus, wsClient.connectionStatus) { pollStatus, wsStatus ->
                when {
                    wsStatus == ConnectionStatus.CONNECTED || pollStatus == ConnectionStatus.CONNECTED -> ConnectionStatus.CONNECTED
                    wsStatus == ConnectionStatus.CONNECTING || pollStatus == ConnectionStatus.CONNECTING -> ConnectionStatus.CONNECTING
                    wsStatus == ConnectionStatus.ERROR || pollStatus == ConnectionStatus.ERROR -> ConnectionStatus.ERROR
                    else -> ConnectionStatus.DISCONNECTED
                }
            }.collect { mergedStatus ->
                _connectionStatus.value = mergedStatus
            }
        }

        viewModelScope.launch {
            combine(pollingClient.botState, wsClient.botState, wsClient.connectionStatus) { pollState, wsState, wsStatus ->
                if (
                    wsStatus == ConnectionStatus.CONNECTED ||
                    wsState.isConnected ||
                    wsState.balance != 0.0 ||
                    wsState.positions.isNotEmpty() ||
                    wsState.trades.isNotEmpty()
                ) {
                    wsState
                } else {
                    pollState
                }
            }.collect { mergedState ->
                _botState.value = mergedState
            }
        }

        viewModelScope.launch {
            merge(pollingClient.errors, wsClient.errors).collect { error ->
                _errors.emit(error)
            }
        }

        connect()
    }
    
    fun connect() {
        // Start HTTP polling as primary
        pollingClient.start()
        // Also start WebSocket as fallback
        wsClient.connect()
    }
    
    fun disconnect() {
        pollingClient.stop()
        wsClient.disconnect()
    }
    
    fun toggleBot(botName: String, enable: Boolean) {
        wsClient.toggleBot(botName, enable)
    }
    
    fun refresh() {
        wsClient.requestFullState()
    }
    
    fun navigateTo(screen: Screen) {
        _currentScreen.value = screen
    }

    fun saveServerConfig(config: ServerConfig) {
        preferencesManager.saveServerConfig(config)
        _serverConfig.value = config
        pollingClient.stop()
        wsClient.reconnect(config.getUrl())
        _currentScreen.value = Screen.Dashboard
    }
    
    override fun onCleared() {
        disconnect()
        super.onCleared()
    }
}

class MainActivity : ComponentActivity() {
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        
        setContent {
            KiBotTheme {
                KiBotApp()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KiBotApp() {
    // Get context INSIDE body, not as parameter default
    val context = androidx.compose.ui.platform.LocalContext.current
    
    // Get ViewModel
    val viewModel: KiBotViewModel = viewModel()
    
    val botState by viewModel.botState.collectAsState()
    val connectionStatus by viewModel.connectionStatus.collectAsState()
    val currentScreen by viewModel.currentScreen.collectAsState()
    val serverConfig by viewModel.serverConfig.collectAsState()
    val shouldShowBootFallback = remember(botState, connectionStatus) {
        val bootLikeState =
            botState.connectedBotId.equals("unknown", ignoreCase = true) &&
                botState.balance == 0.0 &&
                botState.positions.isEmpty() &&
                botState.trades.isEmpty() &&
                botState.assetAllocation.isEmpty()
        bootLikeState || connectionStatus != ConnectionStatus.CONNECTED
    }
    
    var showConfirmDialog by remember { mutableStateOf(false) }
    var pendingBotToggle by remember { mutableStateOf<Pair<String, Boolean>?>(null) }
    
    val snackbarHostState = remember { SnackbarHostState() }
    
    // Error handling
    LaunchedEffect(Unit) {
        viewModel.errors.collect { error ->
            snackbarHostState.showSnackbar(
                message = error,
                duration = SnackbarDuration.Short
            )
        }
    }
    
    // Update widget with real-time data
    LaunchedEffect(botState) {
        KiBotWidgetHelper.updateWidgetData(
            context = context,
            botState = botState
        )
    }
    
    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .background(DarkBackground),
        containerColor = DarkBackground,
        snackbarHost = {
            SnackbarHost(snackbarHostState) { data ->
                Snackbar(
                    snackbarData = data,
                    containerColor = DarkSurfaceVariant,
                    contentColor = TextPrimary,
                    actionColor = KiBotBlue
                )
            }
        },
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = "KiBot",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                            color = TextPrimary
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        
                        // Connection indicator
                        ConnectionIndicator(
                            status = connectionStatus
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { viewModel.navigateTo(Screen.Settings) }) {
                        Icon(
                            imageVector = Icons.Default.Settings,
                            contentDescription = "Settings",
                            tint = KiBotBlue
                        )
                    }
                    IconButton(onClick = { viewModel.refresh() }) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "Refresh",
                            tint = KiBotBlue
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = DarkBackground,
                    titleContentColor = TextPrimary
                )
            )
        },
        bottomBar = {
            NavigationBar(
                containerColor = DarkSurface,
                contentColor = TextPrimary
            ) {
                val screens = listOf(Screen.Dashboard, Screen.Portfolio, Screen.Ledger)
                
                screens.forEach { screen ->
                    val selected = currentScreen == screen
                    
                    NavigationBarItem(
                        selected = selected,
                        onClick = { viewModel.navigateTo(screen) },
                        icon = {
                            Icon(
                                imageVector = if (selected) screen.selectedIcon else screen.unselectedIcon,
                                contentDescription = screen.title
                            )
                        },
                        label = {
                            Text(
                                text = screen.title,
                                style = MaterialTheme.typography.labelSmall
                            )
                        },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = KiBotBlue,
                            selectedTextColor = KiBotBlue,
                            unselectedIconColor = TextSecondary,
                            unselectedTextColor = TextSecondary,
                            indicatorColor = KiBotBlue.copy(alpha = 0.15f)
                        )
                    )
                }
            }
        }
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            AnimatedContent(
                targetState = currentScreen,
                transitionSpec = {
                    fadeIn(animationSpec = tween(200)) togetherWith
                            fadeOut(animationSpec = tween(200))
                },
                label = "screenTransition"
            ) { screen ->
                when (screen) {
                    Screen.Dashboard -> {
                        DashboardScreen(
                            botState = botState,
                            isConnected = connectionStatus == ConnectionStatus.CONNECTED,
                            onToggleBot = { botName, enable ->
                                // Show confirmation dialog before toggling
                                pendingBotToggle = botName to enable
                                showConfirmDialog = true
                            },
                            onRefresh = { viewModel.refresh() }
                        )
                    }
                    Screen.Portfolio -> {
                        PortfolioScreen(
                            botState = botState
                        )
                    }
                    Screen.Ledger -> {
                        LedgerScreen(
                            trades = botState.trades
                        )
                    }
                    Screen.Settings -> {
                        SettingsScreen(
                            currentConfig = serverConfig,
                            onSave = viewModel::saveServerConfig,
                            onBack = { viewModel.navigateTo(Screen.Dashboard) }
                        )
                    }
                }
            }

            if (shouldShowBootFallback) {
                BootFallbackOverlay(
                    connectionStatus = connectionStatus,
                    statusMessage = botState.statusMessage,
                    healthSummary = botState.healthSummary,
                    onRefresh = { viewModel.refresh() },
                    onOpenSettings = { viewModel.navigateTo(Screen.Settings) }
                )
            }
        }
        
        // Confirmation dialog for bot toggle
        if (showConfirmDialog && pendingBotToggle != null) {
            val (botName, enable) = pendingBotToggle!!
            AlertDialog(
                onDismissRequest = {
                    showConfirmDialog = false
                    pendingBotToggle = null
                },
                icon = {
                    Icon(
                        imageVector = if (enable) Icons.Default.PlayArrow else Icons.Default.Stop,
                        contentDescription = null,
                        tint = if (enable) ProfitGreen else LossRed
                    )
                },
                title = {
                    Text(
                        text = if (enable) "Enable $botName?" else "Disable $botName?",
                        color = TextPrimary
                    )
                },
                text = {
                    Text(
                        text = if (enable) {
                            "Bot akan mulai trading secara otomatis. Pastikan market dalam kondisi baik."
                        } else {
                            "⚠️ EMERGENCY STOP\n\nBot akan berhenti entry baru. Posisi yang sudah ada tetap dikelola trailing stop lokal.\n\nLanjutkan?"
                        },
                        color = TextSecondary
                    )
                },
                confirmButton = {
                    Button(
                        onClick = {
                            viewModel.toggleBot(botName, enable)
                            showConfirmDialog = false
                            pendingBotToggle = null
                        },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (enable) ProfitGreen else LossRed
                        )
                    ) {
                        Text(if (enable) "Enable" else "Stop Bot")
                    }
                },
                dismissButton = {
                    TextButton(
                        onClick = {
                            showConfirmDialog = false
                            pendingBotToggle = null
                        }
                    ) {
                        Text("Batal", color = TextSecondary)
                    }
                },
                containerColor = DarkSurface,
                titleContentColor = TextPrimary,
                textContentColor = TextSecondary
            )
        }
    }
}

@Composable
private fun BootFallbackOverlay(
    connectionStatus: ConnectionStatus,
    statusMessage: String,
    healthSummary: String,
    onRefresh: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(DarkBackground.copy(alpha = 0.96f))
            .padding(24.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier
                .fillMaxWidth()
                .border(1.dp, DarkSurfaceVariant, MaterialTheme.shapes.large)
                .background(DarkSurface, MaterialTheme.shapes.large)
                .padding(24.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Memory,
                contentDescription = null,
                tint = KiBotBlue,
                modifier = Modifier.size(48.dp)
            )
            Text(
                text = "KiBot sedang nyambung",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = TextPrimary,
                textAlign = TextAlign.Center
            )
            Text(
                text = when (connectionStatus) {
                    ConnectionStatus.CONNECTED -> "Server sudah nyambung. Menunggu data pertama masuk."
                    ConnectionStatus.CONNECTING -> "Lagi connect ke server KiBot."
                    ConnectionStatus.DISCONNECTED -> "Koneksi ke server putus sebentar."
                    ConnectionStatus.ERROR -> "App kena error koneksi. Coba refresh atau cek settings."
                },
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary,
                textAlign = TextAlign.Center
            )
            if (statusMessage.isNotBlank()) {
                Text(
                    text = statusMessage,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                    textAlign = TextAlign.Center
                )
            }
            if (healthSummary.isNotBlank() && !healthSummary.equals("Menunggu snapshot server.", ignoreCase = true)) {
                Text(
                    text = healthSummary,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary,
                    textAlign = TextAlign.Center
                )
            }
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                OutlinedButton(
                    onClick = onOpenSettings,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = KiBotBlue)
                ) {
                    Text("Settings")
                }
                Button(
                    onClick = onRefresh,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = KiBotBlue, contentColor = Color.White)
                ) {
                    Text("Refresh")
                }
            }
        }
    }
}

@Composable
private fun ConnectionIndicator(
    status: ConnectionStatus
) {
    val (color, text) = when (status) {
        ConnectionStatus.CONNECTED -> StatusOnline to "Server online"
        ConnectionStatus.CONNECTING -> StatusDegraded to "Server connecting..."
        ConnectionStatus.DISCONNECTED -> StatusOffline to "Server offline"
        ConnectionStatus.ERROR -> StatusOffline to "Server error"
    }
    
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .background(
                color = color.copy(alpha = 0.15f),
                shape = MaterialTheme.shapes.small
            )
            .padding(horizontal = 8.dp, vertical = 4.dp)
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(color = color, shape = MaterialTheme.shapes.small)
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = color
        )
    }
}
