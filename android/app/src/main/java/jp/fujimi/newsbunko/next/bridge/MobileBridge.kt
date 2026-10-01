package jp.fujimi.newsbunko.next.bridge

import android.app.Activity
import android.app.AlarmManager
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.webkit.JavascriptInterface
import android.webkit.WebView
import jp.fujimi.newsbunko.next.dictionary.DictionaryRepository
import jp.fujimi.newsbunko.next.settings.LocalSettingsApi
import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog
import jp.fujimi.newsbunko.next.settings.PcEndpoint
import jp.fujimi.newsbunko.next.settings.SecretStore
import jp.fujimi.newsbunko.next.settings.SettingsBackend
import jp.fujimi.newsbunko.next.speech.EdgeSpeechPlayer
import jp.fujimi.newsbunko.next.store.ApiResponse
import jp.fujimi.newsbunko.next.store.LocalLibraryApi
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import javax.net.ssl.SSLException

class MobileBridge(private val activity: Activity, private val webView: WebView) {
    private val context = activity.applicationContext
    private val preferences = context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE)
    private val executor = Executors.newFixedThreadPool(2)
    private val main = Handler(Looper.getMainLooper())
    private val dataRoot = File(context.filesDir, "data").also { it.mkdirs() }
    private val library = LocalLibraryApi(dataRoot.toPath())
    private val dictionary = DictionaryRepository(context)
    private val secrets = SecretStore(context)
    private val speech = EdgeSpeechPlayer(context) { id, event -> deliverTts(id, event) }
    private val settings = LocalSettingsApi(object : SettingsBackend {
        override fun read(key: String) = preferences.getString("setting:$key", null)
        override fun write(key: String, value: String) {
            check(preferences.edit().putString("setting:$key", value).commit()) { "设置保存失败，请检查可用空间。" }
        }
    }) { EdgeVoiceCatalog.voices() }
    private val connectionGeneration = AtomicLong()
    private val speechGeneration = AtomicLong()
    @Volatile private var closed = false
    @Volatile private var windowsStatus = if (preferences.getString("server-url", "").isNullOrEmpty()) "unconfigured" else "offline"
    @Volatile private var connectionDetail = ""
    @Volatile private var connection: HttpURLConnection? = null

    @JavascriptInterface
    fun request(payload: String, callbackId: String) {
        if (closed) return
        if (payload.length > 1024 * 1024) return deliver(callbackId, 413, JSONObject().put("detail", "请求过大，请使用原生文件导入。").toString())
        executor.execute {
            val result = try {
                val request = JSONObject(payload)
                val method = request.optString("method", "GET")
                val path = request.getString("path")
                require(path.startsWith("/api/") && !path.contains('#'))
                val body = if (request.isNull("body")) null else request.optString("body")
                when (path.substringBefore('?')) {
                    "/api/health" -> ApiResponse(200, JSONObject().put("status", "ok").put("runtime", "android")
                        .put("dictionary", true).put("translation_configured", secrets.isConfigured())
                        .put("tts", "browser").put("tts_details", JSONObject().put("enabled", false))
                        .put("capabilities", JSONObject().put("system_speech", false).put("edge_speech", true).put("sync", false).put("daily_generation", false).put("reference_voices", false)).toString())
                    "/api/tasks/daily" -> ApiResponse(200, JSONObject().put("status", "idle").put("stage", "idle").put("message", "Android 日刊采集尚未接入。").toString())
                    else -> settings.request(method, path, body) ?: dictionary.request(method, path) ?: library.request(method, path)
                }
            } catch (_: Exception) {
                ApiResponse(400, JSONObject().put("detail", "请求或设置未能保存，请检查格式与可用空间。").toString())
            }
            deliver(callbackId, result.status, result.body)
        }
    }

    @JavascriptInterface
    fun mobileStatus(): String = JSONObject()
        .put("app_version", context.packageManager.getPackageInfo(context.packageName, 0).versionName)
        .put("data_path", dataRoot.absolutePath)
        .put("server_url", preferences.getString("server-url", ""))
        .put("windows_status", windowsStatus).put("connection_detail", connectionDetail)
        .put("sync_available", false).put("sync_state", "unavailable")
        .put("sync_stage", "协同同步尚未接入").put("sync_detail", "配对与文库合并尚未完成；连接检测不会传输文库。")
        .put("sync_progress", 0).put("pending_changes", 0).put("cache_bytes", 0)
        .put("deepseek_configured", secrets.isConfigured())
        .put("allow_cellular", preferences.getBoolean("allow-cellular", false))
        .put("exact_alarm", Build.VERSION.SDK_INT < 31 || context.getSystemService(AlarmManager::class.java).canScheduleExactAlarms())
        .put("scheduler_available", false).put("next_alarm", JSONObject.NULL)
        .put("irodori_available", false).put("daily_generation_available", false).put("reference_voices_available", false)
        .put("edge_voices_available", true)
        .toString()

    @JavascriptInterface fun setAllowCellular(value: Boolean): Boolean = preferences.edit().putBoolean("allow-cellular", value).commit()
    @JavascriptInterface fun setDeepSeekKey(value: String): Boolean = secrets.saveDeepSeekKey(value.trim())
    @JavascriptInterface fun clearDeepSeekKey(): Boolean = secrets.clearDeepSeekKey()
    @JavascriptInterface fun syncNow(): Boolean = false
    @JavascriptInterface fun resolveMediaUrl(value: String): String = if (value.startsWith("/api/")) "https://appassets.androidplatform.net$value" else ""
    @JavascriptInterface fun queueChange(entity: String, action: String, payload: String): String = ""

    @JavascriptInterface
    fun setServerUrl(value: String): Boolean {
        val normalized = try { if (value.isBlank()) "" else PcEndpoint.normalize(value) } catch (_: Exception) { return false }
        connectionGeneration.incrementAndGet()
        connection?.disconnect()
        val saved = preferences.edit().putString("server-url", normalized).commit()
        if (saved) { windowsStatus = if (normalized.isEmpty()) "unconfigured" else "offline"; connectionDetail = "" }
        return saved
    }

    @JavascriptInterface
    fun connectServer(value: String, callbackId: String) {
        val endpoint = try { PcEndpoint.normalize(value) } catch (_: Exception) {
            deliverSetup(callbackId, false, "请输入 HTTPS 私网 IP 地址，例如 https://192.168.1.20:8429。")
            return
        }
        if (!setServerUrl(endpoint)) { deliverSetup(callbackId, false, "地址保存失败。"); return }
        val generation = connectionGeneration.get()
        windowsStatus = "checking"
        executor.execute {
            var success = false
            val detail = try {
                requireNetwork()
                val client = URL("$endpoint/api/sync/v2/info").openConnection() as HttpURLConnection
                connection = client
                try {
                    client.connectTimeout = 8000
                    client.readTimeout = 8000
                    client.instanceFollowRedirects = false
                    client.setRequestProperty("Accept", "application/json")
                    when (client.responseCode) {
                        401, 403 -> "节点要求设备配对，当前版本尚未完成配对功能。"
                        200 -> {
                            val info = client.inputStream.use { input ->
                                val output = java.io.ByteArrayOutputStream()
                                val buffer = ByteArray(4096)
                                while (true) {
                                    val size = input.read(buffer)
                                    if (size < 0) break
                                    require(output.size() + size <= 64 * 1024)
                                    output.write(buffer, 0, size)
                                }
                                JSONObject(String(output.toByteArray(), Charsets.UTF_8))
                            }
                            if (info.optInt("protocol_version") != 2 || !info.optBoolean("preserve_relative_paths")) "节点协议不兼容，需更新 PC 协同版本。"
                            else { success = true; "HTTPS 节点检测通过；文库同步与配对尚未接入。" }
                        }
                        else -> "节点未提供兼容的协同接口（HTTP ${client.responseCode}）。"
                    }
                } finally { client.disconnect(); connection = null }
            } catch (_: SSLException) { "TLS 证书验证失败，请检查 PC 证书及设备信任配置。" }
            catch (error: IllegalStateException) { error.message ?: "网络不可用。" }
            catch (_: Exception) { "无法连接节点，请检查 HTTPS 地址、网络和 PC 服务。地址已保存。" }
            if (connectionGeneration.get() != generation || closed) return@execute
            windowsStatus = if (success) "ready" else "offline"
            connectionDetail = detail
            deliverSetup(callbackId, success, detail)
        }
    }

    private fun requireNetwork() {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val capabilities = manager.getNetworkCapabilities(manager.activeNetwork) ?: error("当前没有可用网络，地址已保存。")
        if (!preferences.getBoolean("allow-cellular", false) && !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) error("当前网络按流量计费；请开启“允许蜂窝网络”后重试。地址已保存。")
    }

    @JavascriptInterface
    fun requestExactAlarmPermission(): Boolean {
        if (Build.VERSION.SDK_INT < 31) return true
        main.post {
            try { activity.startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${context.packageName}"))) }
            catch (_: Exception) { webView.evaluateJavascript("window.__fujimiNativeNotice?.('系统无法打开精确闹钟设置。')", null) }
        }
        return true
    }

    @JavascriptInterface fun speak(text: String, rate: Float, utteranceId: String) {
        speakWithVoice(text, rate, utteranceId, "")
    }
    @JavascriptInterface fun speakWithVoice(text: String, rate: Float, utteranceId: String, voiceName: String) {
        if (closed) return
        if (text.length > 200000) return deliverTts(utteranceId, "error")
        val generation = speechGeneration.incrementAndGet()
        executor.execute {
            if (generation != speechGeneration.get()) return@execute deliverTts(utteranceId, "stop")
            val selectedVoice = voiceName.ifEmpty { settings.value("voice-mode").optString("browser_voice_name", EdgeVoiceCatalog.KEITA) }
            try { speech.speak(text, rate, utteranceId, selectedVoice) }
            catch (_: Exception) { deliverTts(utteranceId, "error") }
        }
    }
    @JavascriptInterface fun stopSpeaking() { speechGeneration.incrementAndGet(); speech.stop() }

    private fun script(value: String) { main.post { if (!closed) webView.evaluateJavascript(value, null) } }
    private fun deliver(id: String, code: Int, body: String) = script("window.__fujimiMobileResolve?.(${JSONObject.quote(id)},$code,${JSONObject.quote(body)})")
    private fun deliverTts(id: String, event: String) = script("window.__fujimiTtsEvent?.(${JSONObject.quote(id)},${JSONObject.quote(event)})")
    private fun deliverSetup(id: String, success: Boolean, detail: String) = script("window.__fujimiSetupResolve?.(${JSONObject.quote(id)},$success,${JSONObject.quote(detail)})")

    fun close() {
        closed = true
        connectionGeneration.incrementAndGet()
        connection?.disconnect()
        executor.shutdownNow()
        speech.close()
        dictionary.close()
    }
}
