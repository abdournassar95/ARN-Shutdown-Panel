package com.example.network

import android.content.Context
import android.net.wifi.WifiManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress

data class DiscoveredHost(
    val ip: String,
    val port: Int,
    val pcName: String
)

class UDPDiscoveryManager(private val context: Context) {

    private var multicastLock: WifiManager.MulticastLock? = null
    private var job: Job? = null

    fun startListening(onHostDiscovered: (DiscoveredHost) -> Unit) {
        stop()
        job = CoroutineScope(Dispatchers.IO).launch {
            var socket: DatagramSocket? = null
            try {
                val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                multicastLock = wifiManager?.createMulticastLock("ARN_Shutdown_UDP_Lock")?.apply {
                    setReferenceCounted(true)
                    acquire()
                }

                socket = DatagramSocket(null).apply {
                    reuseAddress = true
                    broadcast = true
                    soTimeout = 2500
                    bind(InetSocketAddress(44444))
                }

                val buffer = ByteArray(2048)
                val discoveredIps = mutableSetOf<String>()

                while (isActive) {
                    try {
                        val packet = DatagramPacket(buffer, buffer.size)
                        socket.receive(packet)
                        val text = String(packet.data, 0, packet.length, Charsets.UTF_8).trim()

                        try {
                            val json = JSONObject(text)
                            if (json.optString("app") == "ShutdownPanel") {
                                val hostIp = packet.address?.hostAddress ?: ""
                                val port = json.optInt("port", 8080)
                                val name = json.optString("name", "Windows PC")

                                if (hostIp.isNotEmpty()) {
                                    val key = "$hostIp:$port"
                                    if (!discoveredIps.contains(key)) {
                                        discoveredIps.add(key)
                                        withContext(Dispatchers.Main) {
                                            onHostDiscovered(DiscoveredHost(hostIp, port, name))
                                        }
                                    }
                                }
                            }
                        } catch (_: Exception) {
                            // Non-json or unrecognized packet
                        }
                    } catch (_: java.net.SocketTimeoutException) {
                        // Periodic socket timeout to check isActive condition
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            } finally {
                try {
                    socket?.close()
                } catch (_: Exception) {}
                try {
                    if (multicastLock?.isHeld == true) {
                        multicastLock?.release()
                    }
                } catch (_: Exception) {}
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        try {
            if (multicastLock?.isHeld == true) {
                multicastLock?.release()
            }
        } catch (_: Exception) {}
    }
}
