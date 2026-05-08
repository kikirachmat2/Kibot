package com.kibot.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.kibot.android.data.ServerConfig
import com.kibot.android.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    currentConfig: ServerConfig,
    onSave: (ServerConfig) -> Unit,
    onBack: () -> Unit
) {
    var host by remember { mutableStateOf(currentConfig.host) }
    var port by remember { mutableStateOf(currentConfig.port.toString()) }
    var token by remember { mutableStateOf(currentConfig.dashboardAuthToken) }
    var isSaving by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(DarkBackground)
    ) {
        // Header
        TopAppBar(
            title = { Text("Settings", color = TextPrimary) },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(
                        Icons.Default.ArrowBack,
                        contentDescription = "Back",
                        tint = KiBotBlue
                    )
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(
                containerColor = DarkSurface
            )
        )

        // Content
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp)
        ) {
            Text(
                "Server Configuration",
                style = MaterialTheme.typography.titleMedium,
                color = TextPrimary,
                modifier = Modifier.padding(bottom = 16.dp)
            )

            // Server Host
            OutlinedTextField(
                value = host,
                onValueChange = { host = it },
                label = { Text("Server Host/IP") },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 12.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedBorderColor = KiBotBlue,
                    unfocusedBorderColor = TextSecondary,
                    focusedLabelColor = KiBotBlue,
                    unfocusedLabelColor = TextSecondary,
                    cursorColor = KiBotBlue
                ),
                singleLine = true
            )

            // Server Port
            OutlinedTextField(
                value = port,
                onValueChange = { port = it },
                label = { Text("Server Port") },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 16.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedBorderColor = KiBotBlue,
                    unfocusedBorderColor = TextSecondary,
                    focusedLabelColor = KiBotBlue,
                    unfocusedLabelColor = TextSecondary,
                    cursorColor = KiBotBlue
                ),
                singleLine = true
            )

            // Dashboard Auth Token (optional, but required for non-local servers)
            OutlinedTextField(
                value = token,
                onValueChange = { token = it },
                label = { Text("Dashboard Auth Token") },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 16.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedBorderColor = KiBotBlue,
                    unfocusedBorderColor = TextSecondary,
                    focusedLabelColor = KiBotBlue,
                    unfocusedLabelColor = TextSecondary,
                    cursorColor = KiBotBlue
                ),
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true
            )

            // Message
            if (message.isNotEmpty()) {
                Text(
                    message,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (message.contains("saved", ignoreCase = true)) ProfitGreen else LossRed,
                    modifier = Modifier.padding(bottom = 12.dp)
                )
            }

            // Save Button
            Button(
                onClick = {
                    try {
                        val portNum = port.toIntOrNull()
                        if (host.isNotBlank() && portNum != null && portNum > 0) {
                            isSaving = true
                            val newConfig = ServerConfig(host = host.trim(), port = portNum, dashboardAuthToken = token.trim())
                            onSave(newConfig)
                            message = "Settings saved!"
                            isSaving = false
                        } else {
                            message = "Invalid host or port"
                        }
                    } catch (e: Exception) {
                        message = "Error: ${e.message}"
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                colors = ButtonDefaults.buttonColors(containerColor = KiBotBlue),
                enabled = !isSaving
            ) {
                if (isSaving) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        color = Color.White,
                        strokeWidth = 2.dp
                    )
                } else {
                    Text("Save Settings", color = Color.White)
                }
            }

            // Default Notice
            Text(
                "Default: 168.110.201.228:8787 (legacy direct)\n" +
                "USB fallback: 127.0.0.1:18787 / 18798 (adb reverse -> Batam command center)\n" +
                "Batam control center: 127.0.0.1:18080 (via SSH tunnel)\n" +
                "Alt: 100.103.77.10:9998 (internal; needs VPN/tunnel)\n" +
                "Token hanya kalau server minta",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary,
                modifier = Modifier.padding(top = 16.dp)
            )
        }
    }
}
