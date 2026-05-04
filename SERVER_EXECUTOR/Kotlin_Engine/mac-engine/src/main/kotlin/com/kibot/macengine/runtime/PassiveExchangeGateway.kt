package com.kibot.macengine.runtime

import com.kibot.core.ExchangeGateway
import com.kibot.shared.models.BalanceSnapshot
import com.kibot.shared.models.ClientOrderId
import com.kibot.shared.models.ExecutionPlan
import com.kibot.shared.models.FillSnapshot
import com.kibot.shared.models.MarketQuote
import com.kibot.shared.models.OrderSnapshot
import com.kibot.shared.models.PairId

class PassiveExchangeGateway : ExchangeGateway {
    override suspend fun ping(): Boolean = false

    override suspend fun fetchMarketQuotes(): List<MarketQuote> = emptyList()

    override suspend fun fetchBalances(): List<BalanceSnapshot> = emptyList()

    override suspend fun fetchOpenOrders(): List<OrderSnapshot> = emptyList()

    override suspend fun fetchRecentFills(pairId: PairId?, limit: Int): List<FillSnapshot> = emptyList()

    override suspend fun placeOrder(plan: ExecutionPlan, clientOrderId: ClientOrderId): OrderSnapshot {
        error("Passive exchange gateway cannot place orders.")
    }

    override suspend fun cancelOrder(clientOrderId: ClientOrderId): Boolean = false
}
