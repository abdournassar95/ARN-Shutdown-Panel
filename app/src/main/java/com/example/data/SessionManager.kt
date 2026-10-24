package com.example.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject

data class ServerSession(
    val ip: String,
    val port: Int,
    val name: String,
    val username: String,
    val passwordHash: String, // Stored password or hash for silent auto re-authentication
    val token: String,
    val lastActive: Long = System.currentTimeMillis()
)

class SessionManager(context: Context) {

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs = EncryptedSharedPreferences.create(
        context,
        "arn_shutdown_secure_sessions",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    companion object {
        private const val KEY_LAST_IP = "last_server_ip"
        private const val KEY_LAST_PORT = "last_server_port"
        private const val KEY_SESSIONS = "all_sessions"
    }

    fun saveSession(session: ServerSession) {
        prefs.edit().apply {
            putString(KEY_LAST_IP, session.ip)
            putInt(KEY_LAST_PORT, session.port)

            val list = getAllSessions().toMutableList()
            list.removeAll { it.ip == session.ip && it.port == session.port }
            list.add(0, session)

            val array = JSONArray()
            list.take(5).forEach { s ->
                array.put(JSONObject().apply {
                    put("ip", s.ip)
                    put("port", s.port)
                    put("name", s.name)
                    put("username", s.username)
                    put("passwordHash", s.passwordHash)
                    put("token", s.token)
                    put("lastActive", s.lastActive)
                })
            }
            putString(KEY_SESSIONS, array.toString())
            apply()
        }
    }

    fun getLastSession(): ServerSession? {
        val all = getAllSessions()
        if (all.isEmpty()) return null
        val lastIp = prefs.getString(KEY_LAST_IP, null) ?: return all.firstOrNull()
        val lastPort = prefs.getInt(KEY_LAST_PORT, 8080)
        return all.find { it.ip == lastIp && it.port == lastPort } ?: all.firstOrNull()
    }

    fun getAllSessions(): List<ServerSession> {
        val raw = prefs.getString(KEY_SESSIONS, null) ?: return emptyList()
        val list = mutableListOf<ServerSession>()
        try {
            val array = JSONArray(raw)
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                list.add(
                    ServerSession(
                        ip = obj.getString("ip"),
                        port = obj.getInt("port"),
                        name = obj.optString("name", "Unknown PC"),
                        username = obj.optString("username", "admin"),
                        passwordHash = obj.optString("passwordHash", ""),
                        token = obj.optString("token", ""),
                        lastActive = obj.optLong("lastActive", 0L)
                    )
                )
            }
        } catch (_: Exception) {}
        return list
    }

    fun clearSession(ip: String, port: Int) {
        val list = getAllSessions().toMutableList()
        list.removeAll { it.ip == ip && it.port == port }
        val array = JSONArray()
        list.forEach { s ->
            array.put(JSONObject().apply {
                put("ip", s.ip)
                put("port", s.port)
                put("name", s.name)
                put("username", s.username)
                put("passwordHash", s.passwordHash)
                put("token", s.token)
                put("lastActive", s.lastActive)
            })
        }
        prefs.edit().apply {
            putString(KEY_SESSIONS, array.toString())
            if (prefs.getString(KEY_LAST_IP, "") == ip && prefs.getInt(KEY_LAST_PORT, 0) == port) {
                remove(KEY_LAST_IP)
                remove(KEY_LAST_PORT)
            }
            apply()
        }
    }
}
