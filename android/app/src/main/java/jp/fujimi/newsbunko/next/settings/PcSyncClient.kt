package jp.fujimi.newsbunko.next.settings

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest

/** All cleartext connections are restricted to a user-selected RFC1918 literal by PcEndpoint. */
class PcSyncClient(value: String, private val token: String = "") {
    private val endpoint = PcEndpoint.normalize(value)

    fun json(path: String, body: JSONObject? = null): JSONObject {
        val client = open(path, if (body == null) "GET" else "POST")
        try {
            if (body != null) {
                val bytes = body.toString().toByteArray(Charsets.UTF_8)
                client.doOutput = true
                client.setRequestProperty("Content-Type", "application/json")
                client.setFixedLengthStreamingMode(bytes.size)
                client.outputStream.use { it.write(bytes) }
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

    fun download(key: String, destination: Path) {
        val client = open("/api/sync/v2/bundle?key=${URLEncoder.encode(key, "UTF-8")}", "GET")
        try {
            requireSuccess(client)
            val expected = client.getHeaderField("X-Content-SHA256") ?: error("PC 未提供同步包校验值。")
            require(Regex("[a-f0-9]{64}").matches(expected)) { "PC 同步包校验值无效。" }
            val digest = MessageDigest.getInstance("SHA-256")
            client.inputStream.use { input -> Files.newOutputStream(destination).use { output ->
                val buffer = ByteArray(65536)
                var total = 0L
                while (true) {
                    val count = input.read(buffer); if (count < 0) break
                    total += count
                    require(total <= 512L * 1024 * 1024) { "单个同步项目超过 512 MiB。" }
                    output.write(buffer, 0, count)
                    digest.update(buffer, 0, count)
                }
            } }
            require(hex(digest.digest()) == expected) { "同步包校验失败，未导入。" }
        } finally { client.disconnect() }
    }

    fun upload(source: Path): JSONObject {
        require(Files.size(source) <= 512L * 1024 * 1024) { "单个同步项目超过 512 MiB。" }
        val client = open("/api/sync/v2/bundle", "POST")
        try {
            client.doOutput = true
            client.readTimeout = 120000
            client.setRequestProperty("Content-Type", "application/zip")
            val digest = MessageDigest.getInstance("SHA-256")
            Files.newInputStream(source).use { input ->
                val buffer = ByteArray(65536)
                while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
            }
            client.setRequestProperty("X-Content-SHA256", hex(digest.digest()))
            client.setFixedLengthStreamingMode(Files.size(source))
            client.outputStream.use { output -> Files.newInputStream(source).use { it.copyTo(output) } }
            requireSuccess(client)
            return client.inputStream.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText().take(65536)) }
        } finally { client.disconnect() }
    }

    private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it) }

    private fun open(path: String, method: String): HttpURLConnection = (URL("$endpoint$path").openConnection() as HttpURLConnection).apply {
        connectTimeout = 8000
        readTimeout = 30000
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
