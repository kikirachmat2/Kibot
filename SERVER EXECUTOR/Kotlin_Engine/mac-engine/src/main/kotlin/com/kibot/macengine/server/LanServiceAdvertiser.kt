package com.kibot.macengine.server

import java.net.InetAddress
import java.net.NetworkInterface
import java.util.Collections
import javax.jmdns.JmDNS
import javax.jmdns.ServiceInfo

class LanServiceAdvertiser(
    private val host: String,
    private val port: Int,
) {
    private var jmdns: JmDNS? = null
    private var serviceInfo: ServiceInfo? = null

    fun start() {
        if (jmdns != null) return
        val lanHost = detectLanHost(host) ?: return
        val inetAddress = runCatching { InetAddress.getByName(lanHost) }.getOrNull() ?: return
        val service = ServiceInfo.create(
            SERVICE_TYPE,
            SERVICE_NAME,
            port,
            0,
            0,
            mapOf(
                "path" to "/api/lan/ping",
                "role" to "mac-backup",
            ),
        )
        val dns = JmDNS.create(inetAddress, SERVICE_NAME)
        dns.registerService(service)
        jmdns = dns
        serviceInfo = service
    }

    fun stop() {
        val dns = jmdns ?: return
        val service = serviceInfo
        runCatching {
            if (service != null) dns.unregisterService(service)
        }
        runCatching { dns.close() }
        jmdns = null
        serviceInfo = null
    }

    private companion object {
        const val SERVICE_TYPE = "_kibot._tcp.local."
        const val SERVICE_NAME = "KiCryp-Mac-Engine"

        fun detectLanHost(host: String): String? {
            if (host != "0.0.0.0" && host != "127.0.0.1" && host != "localhost") {
                return host
            }
            return runCatching {
                Collections.list(NetworkInterface.getNetworkInterfaces())
                    .asSequence()
                    .filter { it.isUp && !it.isLoopback }
                    .flatMap { Collections.list(it.inetAddresses).asSequence() }
                    .firstOrNull { address -> !address.isLoopbackAddress && address.hostAddress?.contains(':') == false }
                    ?.hostAddress
            }.getOrNull()
        }
    }
}
