package com.kibot.macengine.config

import kotlin.test.Test
import kotlin.test.assertEquals

class MacRuntimeConfigLoaderTest {
    @Test
    fun `resolve env alias candidates supports kibot and kicryp namespaces`() {
        assertEquals(
            listOf("KICRYP_EXCHANGE_KIND", "KIBOT_EXCHANGE_KIND"),
            MacRuntimeConfigLoader.resolveEnvAliasCandidates("KICRYP_EXCHANGE_KIND"),
        )
        assertEquals(
            listOf("KIBOT_RELEASE_LABEL", "KICRYP_RELEASE_LABEL"),
            MacRuntimeConfigLoader.resolveEnvAliasCandidates("KIBOT_RELEASE_LABEL"),
        )
        assertEquals(
            listOf("SUPABASE_URL"),
            MacRuntimeConfigLoader.resolveEnvAliasCandidates("SUPABASE_URL"),
        )
    }
}
