package com.kibot.macengine.runtime

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.nio.file.Files
import java.nio.file.Path

data class AiProviderStatusSnapshot(
    val successfulProviders: List<String> = emptyList(),
    val skippedProviders: Map<String, String> = emptyMap(),
) {
    val summaryLabel: String = buildString {
        val healthy = successfulProviders.map { it.uppercase() }
        if (healthy.isNotEmpty()) {
            append("AI sehat: ")
            append(healthy.joinToString(", "))
        }
        if (skippedProviders.isNotEmpty()) {
            if (isNotEmpty()) append(" • ")
            append("skip: ")
            append(
                skippedProviders.entries.joinToString(", ") { (provider, reason) ->
                    "${provider.uppercase()}(${reason.replace('_', ' ')})"
                },
            )
        }
        if (isEmpty()) append("AI summary belum siap.")
    }
}

class AiProviderStatusLoader {
    private val json = Json { ignoreUnknownKeys = true }

    fun loadOrDefault(adaptivePolicyPath: Path): AiProviderStatusSnapshot {
        val summaryPath = adaptivePolicyPath.parent?.resolve("summary.json") ?: return AiProviderStatusSnapshot()
        if (!Files.exists(summaryPath)) return AiProviderStatusSnapshot()
        return runCatching {
            val root = json.parseToJsonElement(Files.readString(summaryPath)).jsonObject
            val successful = root["successful_providers"]
                ?.jsonArray
                ?.mapNotNull { element ->
                    element.jsonPrimitive.content
                        .trim()
                        .takeIf { it.isNotBlank() }
                }
                .orEmpty()
            val skipped = root["skipped_providers"]
                ?.jsonObject
                ?.mapValues { (_, value) -> value.jsonPrimitive.content.trim() }
                .orEmpty()
            AiProviderStatusSnapshot(
                successfulProviders = successful,
                skippedProviders = skipped,
            )
        }.getOrDefault(AiProviderStatusSnapshot())
    }
}
