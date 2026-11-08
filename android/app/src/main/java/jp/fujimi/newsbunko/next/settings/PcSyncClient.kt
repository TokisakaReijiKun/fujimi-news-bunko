package jp.fujimi.newsbunko.next.settings

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.Files
import java.nio.file.Path

/** Connections stay restricted to a user-selected RFC1918 or Tailscale IPv4 literal by PcEndpoint. */
class PcSyncClient(value: String, private val token: String = "", private val timeoutMs: Int? = null) {
    private val endpoint = PcEndpoint.normalize(value)

    fun json(path: String, body: JSONObject? = null, method: String = if (body == null) "GET" else "POST"): JSONObject {
        val client = open(path, method)
        try {
            if (path.startsWith("/api/sync/v2/tts/")) client.readTimeout = timeoutMs ?: 600000
            if (body != null) {
                val bytes = body.toString().toByteArray(Charsets.UTF_8)
                client.doOutput = true
                client.setRequestProperty("Content-Type", "application/json")
                client.setFixedLengthStreamingMode(bytes.size)
                client.outputStream.use { it.write(bytes) }
            }
            if (path.startsWith("/api/sync/v2/tts/") && client.responseCode !in 200..299) {
                val detail = runCatching { client.errorStream?.bufferedReader(Charsets.UTF_8)?.use { JSONObject(it.readText().take(8192)).optString("detail") } }.getOrNull()
                throw java.io.IOException(detail?.takeIf { it.isNotBlank() }?.take(500) ?: "PC 朗读请求失败（HTTP ${client.responseCode}）。")
            }
            requireSuccess(client)
            val bytes = client.inputStream.use { input ->
                val out = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    val count = input.read(buffer); if (count < 0) break
                    require(out.size() + count <= 8 * 1024 * 1024) { "PC 返回的清单过大。" }
                    out.write(buffer, 0, count)
                }
                out.toByteArray()
            }
            return JSONObject(String(bytes, Charsets.UTF_8))
        } finally { client.disconnect() }
    }

    fun download(key: String, destination: Path, knownFiles: JSONObject = JSONObject()) {
        val client = open("/api/sync/v2/pull", "POST")
        var received = 0L
        try {
            val payload = JSONObject().put("key", key).put("known_files", knownFiles).toString().toByteArray(Charsets.UTF_8)
            client.doOutput = true
            client.setRequestProperty("Content-Type", "application/json")
            client.setRequestProperty("Accept", "application/zip")
            client.setFixedLengthStreamingMode(payload.size)
            client.outputStream.use { it.write(payload) }
            requireSuccess(client)
            val expectedSize = client.contentLengthLong
            client.inputStream.use { input -> Files.newOutputStream(destination).use { output ->
                val buffer = ByteArray(65536)
                while (true) {
                    val count = input.read(buffer); if (count < 0) break
                    received += count
                    require(received <= 512L * 1024 * 1024) { "单个同步项目超过 512 MiB。" }
                    output.write(buffer, 0, count)
                }
                require(expectedSize < 0 || received == expectedSize) { "同步包传输未完成，请重试。" }
            } }
        } catch (failure: java.io.IOException) {
            android.util.Log.w("FujimiSync", "Bundle body ended after $received of ${client.contentLengthLong} bytes", failure)
            throw failure
        } finally { client.disconnect() }
    }

    fun upload(source: Path): JSONObject {
        require(Files.size(source) <= 512L * 1024 * 1024) { "单个同步项目超过 512 MiB。" }
        val client = open("/api/sync/v2/bundle", "POST")
        try {
            client.doOutput = true
            client.readTimeout = 120000
            client.setRequestProperty("Content-Type", "application/zip")
            client.setFixedLengthStreamingMode(Files.size(source))
            client.outputStream.use { output -> Files.newInputStream(source).use { it.copyTo(output) } }
            requireSuccess(client)
            return client.inputStream.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText().take(65536)) }
        } finally { client.disconnect() }
    }

    private fun open(path: String, method: String): HttpURLConnection = (URL("$endpoint$path").openConnection() as HttpURLConnection).apply {
        connectTimeout = timeoutMs ?: 8000
        readTimeout = timeoutMs ?: 30000
        instanceFollowRedirects = false
        requestMethod = method
        setRequestProperty("Accept", "application/json")
        if (token.isNotEmpty()) setRequestProperty("Authorization", "Bearer $token")
    }

    private fun requireSuccess(client: HttpURLConnection) {
        when (val code = client.responseCode) {
            200 -> Unit
            401, 403 -> error("配对码不正确、已过期或设备授权已撤销，请重新配对。")
            409 -> error("此项目存在内容冲突，原文件已保留。")
            429 -> error("配对尝试过多，请稍后重试。")
            503 -> error("PC 正在处理文库任务，请完成后重试。")
            else -> error("PC 同步请求失败（HTTP $code）。")
        }
    }
}
