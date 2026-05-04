package com.kibot.macengine.runtime

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.slf4j.LoggerFactory
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.time.Duration

internal class TelegramAlertNotifier(
    private val enabled: Boolean,
    private val botToken: String?,
    private val chatId: String?,
) {
    private val logger = LoggerFactory.getLogger(TelegramAlertNotifier::class.java)
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    suspend fun send(text: String) {
        if (!enabled) return
        val token = botToken?.takeIf { it.isNotBlank() } ?: return
        val targetChatId = chatId?.takeIf { it.isNotBlank() } ?: return
        val payload = buildString {
            append("chat_id=")
            append(URLEncoder.encode(targetChatId, StandardCharsets.UTF_8))
            append("&text=")
            append(URLEncoder.encode(text, StandardCharsets.UTF_8))
            append("&disable_web_page_preview=true")
        }
        val request = HttpRequest.newBuilder()
            .uri(URI("https://api.telegram.org/bot$token/sendMessage"))
            .timeout(Duration.ofSeconds(8))
            .header("Content-Type", "application/x-www-form-urlencoded")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
            .build()
        runCatching {
            withContext(Dispatchers.IO) {
                http.send(request, HttpResponse.BodyHandlers.ofString())
            }
        }.onFailure { error ->
            logger.warn("Telegram alert failed: {}", error.message ?: "unknown")
        }
    }
}
