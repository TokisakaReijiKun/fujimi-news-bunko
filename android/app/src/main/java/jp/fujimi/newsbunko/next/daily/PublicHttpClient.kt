package jp.fujimi.newsbunko.next.daily

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import jp.fujimi.newsbunko.next.news.NewsPage
import jp.fujimi.newsbunko.next.news.NewsTransport
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.Dns
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.InetAddress
import java.util.concurrent.TimeUnit

data class DownloadedFile(val url: String, val bytes: ByteArray, val contentType: String)

/** TLS and public DNS are checked at each redirect and each actual connection. */
class PublicHttpClient(private val context: Context, private val checkpoint: () -> Unit = {}) : NewsTransport {
    private val cookies = mutableListOf<Cookie>()
    val client: OkHttpClient = OkHttpClient.Builder()
        .followRedirects(false).followSslRedirects(false)
        .connectTimeout(8, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS)
        .callTimeout(40, TimeUnit.SECONDS)
        .dns(object : Dns {
            override fun lookup(hostname: String): List<InetAddress> = Dns.SYSTEM.lookup(hostname).also { addresses ->
                require(addresses.isNotEmpty() && addresses.all(::isPublic)) { "来源网址解析到了非公开地址。" }
            }
        })
        .cookieJar(object : CookieJar {
            override fun saveFromResponse(url: HttpUrl, values: List<Cookie>) = synchronized(cookies) {
                values.forEach { cookie -> cookies.removeAll { it.name == cookie.name && it.domain == cookie.domain && it.path == cookie.path }; cookies.add(cookie) }
                Unit
            }
            override fun loadForRequest(url: HttpUrl): List<Cookie> = synchronized(cookies) {
                cookies.removeAll { it.expiresAt <= System.currentTimeMillis() }
                cookies.filter { it.matches(url) }
            }
        }).build()

    override fun get(url: String): NewsPage {
        val download = download(url, 8 * 1024 * 1024)
        val charset = Regex("charset=([^;\\s]+)", RegexOption.IGNORE_CASE).find(download.contentType)?.groupValues?.get(1)?.trim('"', '\'')
        val encoding = try { charset?.let(java.nio.charset.Charset::forName) ?: Charsets.UTF_8 } catch (_: Exception) { Charsets.UTF_8 }
        return NewsPage(url, download.url, String(download.bytes, encoding))
    }

    fun download(url: String, limit: Int): DownloadedFile {
        var address = checkedUrl(url)
        repeat(6) { redirects ->
            checkpoint(); requireNetwork(context)
            val request = Request.Builder().url(address)
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36")
                .header("Accept", "text/html,application/json,image/*,video/mp4;q=0.9,*/*;q=0.8")
                .header("Accept-Language", "ja,en;q=0.5").build()
            client.newCall(request).execute().use { response ->
                checkpoint()
                if (response.code in setOf(301, 302, 303, 307, 308)) {
                    require(redirects < 5) { "来源重定向次数过多。" }
                    address = checkedUrl(address.resolve(response.header("Location") ?: error("来源重定向缺少地址。"))?.toString() ?: error("来源重定向地址无效。"))
                } else {
                    if (!response.isSuccessful) throw IOException("来源请求失败（HTTP ${response.code}）。")
                    val body = response.body ?: error("来源返回空内容。")
                    require(body.contentLength() <= limit) { "下载内容超出体积限制。" }
                    val output = ByteArrayOutputStream()
                    body.byteStream().use { input ->
                        val bytes = ByteArray(32 * 1024)
                        while (true) {
                            checkpoint()
                            val read = input.read(bytes)
                            if (read < 0) break
                            require(output.size() + read <= limit) { "下载内容超出体积限制。" }
                            output.write(bytes, 0, read)
                        }
                    }
                    return DownloadedFile(address.toString(), output.toByteArray(), response.header("Content-Type", "") ?: "")
                }
            }
        }
        error("来源重定向次数过多。")
    }

    /** Cookie header for a follow-up request in the same source session. */
    fun cookieHeader(url: String): String = synchronized(cookies) {
        val target = url.toHttpUrl()
        cookies.removeAll { it.expiresAt <= System.currentTimeMillis() }
        cookies.filter { it.matches(target) }.joinToString("; ") { "${it.name}=${it.value}" }
    }

    companion object {
        fun checkedUrl(value: String): HttpUrl = value.toHttpUrl().also {
            require(it.isHttps && it.username.isEmpty() && it.password.isEmpty() && it.port == 443) { "新闻下载仅接受公开 HTTPS 地址。" }
            require(it.host != "localhost" && !it.host.endsWith(".localhost") && !it.host.endsWith(".local")) { "新闻下载不接受本地地址。" }
        }
        fun isPublic(address: InetAddress): Boolean {
            if (address.isAnyLocalAddress || address.isLoopbackAddress || address.isLinkLocalAddress || address.isSiteLocalAddress || address.isMulticastAddress) return false
            val bytes = address.address.map { it.toInt() and 255 }
            if (bytes.size == 4) {
                val (a, b, c) = bytes
                return a !in setOf(0, 10, 127) && a < 224 && !(a == 100 && b in 64..127) &&
                    !(a == 169 && b == 254) && !(a == 172 && b in 16..31) && !(a == 192 && b == 168) &&
                    !(a == 192 && b == 0) && !(a == 192 && b == 2) && !(a == 198 && b in 18..19) &&
                    !(a == 198 && b == 51 && c == 100) && !(a == 203 && b == 0 && c == 113)
            }
            return bytes.size == 16 && bytes[0] in 0x20..0x3f && !(bytes.take(4) == listOf(0x20, 0x01, 0x0d, 0xb8))
        }
        fun requireNetwork(context: Context) {
            val manager = context.getSystemService(ConnectivityManager::class.java)
            val network = manager.getNetworkCapabilities(manager.activeNetwork) ?: error("当前没有可用网络；本次日刊未完成。")
            if (!context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE).getBoolean("allow-cellular", false) &&
                !network.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) error("当前网络按流量计费；需开启“允许蜂窝网络”。")
        }
    }
}
