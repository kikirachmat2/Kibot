package com.kibot.core

import com.kibot.shared.models.PairId

internal data class PairParts(
    val baseAsset: String,
    val quoteAsset: String,
)

internal fun PairId.assets(): PairParts {
    val parts = value.lowercase().split("_")
    return if (parts.size == 2) {
        PairParts(parts[0], parts[1])
    } else {
        val quote = listOf("idr", "usdt", "btc", "eth").firstOrNull { value.lowercase().endsWith(it) }
            ?: error("Unsupported pair format: ${value}")
        PairParts(value.lowercase().removeSuffix(quote), quote)
    }
}

fun correlationFamilyOf(pairId: PairId): String {
    val base = pairId.value.substringBefore('_').lowercase()
    return when (base) {
        in setOf("doge", "shib", "pepe", "floki", "bonk", "wif", "pippin", "neiro", "turbo", "mog", "bome", "brett", "dog", "popcat") -> "meme"
        in setOf("fet", "agix", "ocean", "render", "tao", "ai16z", "grt", "worldcoin", "rndr") -> "ai"
        in setOf("sol", "ada", "avax", "matic", "arb", "op", "eth", "near", "ont", "trx", "xlm", "plpa", "kaito", "dot", "atom", "inj", "sui", "sei", "apt", "ftm", "klay", "cro", "zil") -> "l1_l2"
        in setOf("btc", "stx", "ordi", "sats", "rune", "tia") -> "btc"
        in setOf("uni", "aave", "link", "snx", "crv", "mkr", "comp", "ldo", "gmx", "dydx", "1inch", "cake", "sushi", "pendle", "eigen") -> "defi"
        in setOf("axs", "sand", "mana", "gala", "imx", "ilv", "enjin", "alice", "rmrk", "magic") -> "gaming"
        in setOf("sto", "drx", "d", "cast", "one", "hot", "reef", "btt", "win", "xec", "luna2", "ustc") -> "microcap"
        else -> base
    }
}

fun averageOf(vararg values: Double): Double {
    if (values.isEmpty()) return 0.0
    return values.map { it.coerceIn(0.0, 1.0) }.average().coerceIn(0.0, 1.0)
}

fun weightedAverage(vararg entries: Pair<Double, Double>): Double {
    val totalWeight = entries.sumOf { it.second }.coerceAtLeast(0.000001)
    return (entries.sumOf { it.first.coerceIn(0.0, 1.0) * it.second } / totalWeight).coerceIn(0.0, 1.0)
}
