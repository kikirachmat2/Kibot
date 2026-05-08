package com.kibot.macengine.runtime

import kotlinx.coroutines.delay
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.slf4j.LoggerFactory
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.time.Duration

internal class TelegramCommandPoller(
    private val botToken: String,
    private val allowedChatId: String,
    private val pollIntervalMillis: Long = 5_000L,
) {
    private val logger = LoggerFactory.getLogger(TelegramCommandPoller::class.java)
    private val httpClient: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(6))
        .build()
    private val json = Json { ignoreUnknownKeys = true }
    private var lastUpdateId: Long = 0L

    suspend fun loop(onCommand: suspend (TelegramCommand) -> Unit) {
        while (true) {
            runCatching {
                pollOnce().forEach { command ->
                    onCommand(command)
                }
            }.onFailure { error ->
                logger.debug("Telegram command poll failed: {}", error.message ?: "unknown")
            }
            delay(pollIntervalMillis)
        }
    }

    private fun pollOnce(): List<TelegramCommand> {
        val url = buildString {
            append("https://api.telegram.org/bot")
            append(botToken)
            append("/getUpdates?timeout=0")
            if (lastUpdateId > 0L) {
                append("&offset=")
                append(lastUpdateId + 1L)
            }
            append("&allowed_updates=")
            append(URLEncoder.encode("[\"message\"]", StandardCharsets.UTF_8))
        }
        val request = HttpRequest.newBuilder()
            .uri(URI.create(url))
            .timeout(Duration.ofSeconds(8))
            .GET()
            .build()
        val response = httpClient.send(request, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) return emptyList()
        val payload = runCatching { json.decodeFromString(TelegramUpdatesResponse.serializer(), response.body()) }
            .getOrNull()
            ?: return emptyList()
        if (!payload.ok) return emptyList()
        val commands = mutableListOf<TelegramCommand>()
        payload.result.forEach { update ->
            lastUpdateId = maxOf(lastUpdateId, update.updateId)
            val message = update.message ?: return@forEach
            val chatId = message.chat.id.toString()
            if (chatId != allowedChatId.trim()) return@forEach
            val text = message.text?.trim().orEmpty()
            if (text.isBlank()) return@forEach
            val command = text.lowercase().substringBefore(' ').trim()
            val normalized = when (command) {
                "/status" -> TelegramCommand.Status
                "/pause" -> TelegramCommand.Pause
                "/resume" -> TelegramCommand.Resume
                else -> null
            }
            if (normalized != null) {
                commands += normalized
            }
        }
        return commands
    }
}

internal sealed class TelegramCommand {
    data object Status : TelegramCommand()
    data object Pause : TelegramCommand()
    data object Resume : TelegramCommand()
}

@Serializable
private data class TelegramUpdatesResponse(
    val ok: Boolean,
    val result: List<TelegramUpdate> = emptyList(),
)

@Serializable
private data class TelegramUpdate(
    @SerialName("update_id")
    val updateId: Long,
    val message: TelegramMessage? = null,
)

@Serializable
private data class TelegramMessage(
    val chat: TelegramChat,
    val text: String? = null,
)

@Serializable
private data class TelegramChat(
    val id: Long,
)
