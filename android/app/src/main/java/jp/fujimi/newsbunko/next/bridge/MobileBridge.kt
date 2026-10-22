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
import jp.fujimi.newsbunko.next.daily.DailyRuntime
import jp.fujimi.newsbunko.next.settings.LocalSettingsApi
import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog
import jp.fujimi.newsbunko.next.settings.PcEndpoint
import jp.fujimi.newsbunko.next.settings.PcPairing
import jp.fujimi.newsbunko.next.settings.PcSyncClient
import jp.fujimi.newsbunko.next.settings.SecretStore
import jp.fujimi.newsbunko.next.settings.SettingsBackend
import jp.fujimi.newsbunko.next.speech.EdgeSpeechPlayer
import jp.fujimi.newsbunko.next.speech.ArticleEdgeAudio
import jp.fujimi.newsbunko.next.speech.ArticleMediaPlayer
import jp.fujimi.newsbunko.next.store.ApiResponse
import jp.fujimi.newsbunko.next.store.LocalLibraryApi
import jp.fujimi.newsbunko.next.store.LibrarySyncStore
import jp.fujimi.newsbunko.next.store.LocalVoiceStore
import jp.fujimi.newsbunko.next.storage.DataDirectory
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import javax.net.ssl.SSLException
import com.google.zxing.integration.android.IntentIntegrator
import java.util.UUID
import java.nio.file.Files

class MobileBridge(private val activity: Activity, private val webView: WebView) {
    private val context = activity.applicationContext
    private val preferences = context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE)
    private val executor = Executors.newFixedThreadPool(2)
    private val main = Handler(Looper.getMainLooper())
    private val dataRoot = DataDirectory.prepare(context)
    private val daily = DailyRuntime.get(context)
    private val library by lazy { LocalLibraryApi(dataRoot.toPath(), daily::snapshot, { settings.value("voice-mode") }, settings::browserVoices) }
    private val syncedLibrary by lazy { jp.fujimi.newsbunko.next.store.LocalSyncedLibraryApi(dataRoot.toPath(), { settings.value("voice-mode") }, settings::browserVoices) }
    private val dictionary = DictionaryRepository(context)
    private val secrets = SecretStore(context)
    private val speech = EdgeSpeechPlayer(context) { id, event -> deliverTts(id, event) }
    private val articleAudio = ArticleEdgeAudio(dataRoot.toPath(), speech::completeArticle, speech::validateFile)
    private val media = ArticleMediaPlayer(context, dataRoot.toPath())
    private val settings = LocalSettingsApi(object : SettingsBackend {
        override fun read(key: String) = preferences.getString("setting:$key", null)
        override fun write(key: String, value: String) {
            check(preferences.edit().putString("setting:$key", value).commit()) { "设置保存失败，请检查可用空间。" }
        }
    }, daily.schedule, LocalVoiceStore(dataRoot.toPath())) { EdgeVoiceCatalog.voices() }
    private val connectionGeneration = AtomicLong()
    private val speechGeneration = AtomicLong()
    @Volatile private var closed = false
    @Volatile private var windowsStatus = if (preferences.getString("server-url", "").isNullOrEmpty()) "unconfigured" else "offline"
    @Volatile private var connectionDetail = ""
    @Volatile private var connection: HttpURLConnection? = null
    @Volatile private var scanCallback: String? = null
    @Volatile private var syncAvailable = preferences.getBoolean("pc-sync-available", false)
    @Volatile private var syncState = "idle"
    @Volatile private var syncStage = "尚未同步"
    @Volatile private var syncDetail = "配对后点击立即同步，双向补齐文库内容。"
    @Volatile private var syncProgress = 0

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
                        .put("capabilities", JSONObject().put("system_speech", false).put("edge_speech", true).put("sync", true).put("daily_generation", true).put("reference_voices", true).put("reference_synthesis", false)).toString())
                    else -> edgeAudioRequest(method, path, body) ?: daily.request(method, path) ?: settings.request(method, path, body) ?: dictionary.request(method, path) ?: syncedLibrary.request(method, path, body) ?: library.request(method, path, body)
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
        .put("paired", pairedCredentials() != null)
        .put("sync_available", pairedCredentials() != null && syncAvailable).put("sync_state", if (pairedCredentials() == null) "unavailable" else syncState)
        .put("sync_stage", syncStage).put("sync_detail", syncDetail)
        .put("sync_progress", syncProgress).put("pending_changes", 0).put("cache_bytes", 0)
        .put("deepseek_configured", secrets.isConfigured())
        .put("allow_cellular", preferences.getBoolean("allow-cellular", false))
        .put("exact_alarm", Build.VERSION.SDK_INT < 31 || context.getSystemService(AlarmManager::class.java).canScheduleExactAlarms())
        .put("scheduler_available", true).put("next_alarm", daily.schedule.status().opt("next_run"))
        .put("schedule_precision", daily.schedule.status().optString("schedule_precision", "window"))
        .put("alarm_error", preferences.getString("alarm-error", ""))
        .put("article_index_error", preferences.getString("article-index-error", ""))
        .put("irodori_available", false).put("daily_generation_available", true).put("reference_voices_available", true)
        .put("reference_synthesis_available", false).put("saved_audio_voices_available", true)
        .put("edge_voices_available", true)
        .toString()

    private fun edgeAudioRequest(method: String, path: String, body: String?): ApiResponse? {
        val match = Regex("/api/articles/(\\d+)/edge-tts").matchEntire(path) ?: return null
        if (method != "POST") return ApiResponse(405, JSONObject().put("detail", "请使用 POST 生成音频。").toString())
        val id = match.groupValues[1].toLong()
        val voice = JSONObject(body ?: "{}").optString("voice").ifEmpty {
            settings.value("voice-mode").optString("browser_voice_name", EdgeVoiceCatalog.KEITA)
        }
        if (voice !in setOf(EdgeVoiceCatalog.KEITA, EdgeVoiceCatalog.NANAMI)) return ApiResponse(409,
            JSONObject().put("detail", "此声线须先在 PC 生成完整朗读后同步，Android 不运行其合成模型。").toString())
        return try {
            val saved = articleAudio.generate(id, voice)
            val result = library.request("POST", "/api/articles/$id/reread", JSONObject()
                .put("mode", "browser").put("browser_voice_name", voice).toString())
            if (result.status != 200) result else ApiResponse(200, JSONObject(result.body).put("cached", saved.cached).toString())
        } catch (failure: IllegalArgumentException) {
            ApiResponse(409, JSONObject().put("detail", failure.message ?: "音频与正文不匹配，未保存。").toString())
        } catch (_: Exception) {
            ApiResponse(502, JSONObject().put("detail", "在线声线生成或保存失败，请检查网络与存储空间后重试；已有音频保留。").toString())
        }
    }

    @JavascriptInterface fun setAllowCellular(value: Boolean): Boolean = preferences.edit().putBoolean("allow-cellular", value).commit()
    @JavascriptInterface fun setDeepSeekKey(value: String): Boolean = secrets.saveDeepSeekKey(value.trim())
    @JavascriptInterface fun clearDeepSeekKey(): Boolean = secrets.clearDeepSeekKey()
    @Synchronized
    @JavascriptInterface fun syncNow(): Boolean {
        if (closed || syncState == "running") return false
        val credentials = pairedCredentials() ?: return false
        if (daily.snapshot().optString("status") == "running") {
            syncState = "failed"; syncDetail = "日刊任务正在运行，请完成后再同步。"; return false
        }
        val generation = connectionGeneration.get()
        syncState = "running"; syncStage = "读取文库清单"; syncProgress = 0; syncDetail = "正在检查 PC 连接。"
        executor.execute {
            val work = dataRoot.toPath().resolve("diagnostics/sync-network/${UUID.randomUUID()}")
            val errors = mutableListOf<String>()
            var received = 0; var sent = 0; var completed = 0
            fun checkpoint() {
                check(!closed && generation == connectionGeneration.get()) { "连接已变更，同步已停止。" }
                check(daily.snapshot().optString("status") != "running") { "日刊任务已开始，同步已停止。" }
            }
            try {
                requireNetwork(); checkpoint()
                Files.createDirectories(work)
                val client = PcSyncClient(credentials.getString("url"), credentials.getString("token"))
                val info = client.json("/api/sync/v2/status")
                check(info.optInt("protocol") == 2 && info.optBoolean("sync_available")) { "PC 尚未开启文库同步。" }
                val store = LibrarySyncStore(dataRoot.toPath())
                val local = store.manifest()
                val remote = client.json("/api/sync/v2/manifest")
                require(remote.optInt("version") == 1) { "PC 文库清单版本不兼容。" }
                remote.optJSONArray("browser_voices")?.let(settings::savePcBrowserVoices)
                for (list in listOf(local.optJSONArray("errors"), remote.optJSONArray("errors"))) {
                    if (list != null) for (i in 0 until list.length()) errors += list.opt(i).toString().take(180)
                }
                val downloads = remote.getJSONArray("items"); val uploads = local.getJSONArray("items")
                val total = downloads.length() + uploads.length()
                for (i in 0 until downloads.length()) {
                    checkpoint()
                    val item = downloads.getJSONObject(i)
                    syncStage = "接收 PC 文库"; syncDetail = item.optString("title")
                    val bundle = work.resolve("download.zip")
                    try {
                        client.download(item.getString("key"), bundle); checkpoint()
                        val result = store.importBundle(bundle)
                        if (result.getString("status") == "conflict") errors += "${item.optString("title")}：正文或附件冲突，已保留本机内容。"
                        else if (result.getString("status") != "unchanged") received++
                    } catch (failure: Exception) { errors += "${item.optString("title")}：${failure.message?.take(160) ?: "接收失败"}" }
                    finally { Files.deleteIfExists(bundle) }
                    completed++; syncProgress = if (total == 0) 0 else (completed * 99 / total)
                }
                for (i in 0 until uploads.length()) {
                    checkpoint()
                    val item = uploads.getJSONObject(i)
                    syncStage = "发送手机文库"; syncDetail = item.optString("title")
                    val bundle = work.resolve("upload.zip")
                    try {
                        store.exportBundle(item.getString("key"), bundle); checkpoint()
                        val result = client.upload(bundle)
                        if (result.optString("status") == "conflict") errors += "${item.optString("title")}：PC 已有不同内容，未覆盖。"
                        else if (result.optString("status") in setOf("created", "updated")) sent++
                    } catch (failure: Exception) { errors += "${item.optString("title")}：${failure.message?.take(160) ?: "发送失败"}" }
                    finally { Files.deleteIfExists(bundle) }
                    completed++; syncProgress = if (total == 0) 0 else (completed * 99 / total)
                }
                checkpoint()
                syncState = if (errors.isEmpty()) "completed" else "partial"
                syncStage = if (errors.isEmpty()) "同步完成" else "部分同步完成"
                syncProgress = if (errors.isEmpty()) 100 else 99
                syncDetail = "接收 $received 项，发送 $sent 项。" + if (errors.isEmpty()) "文库已核对。" else errors.take(3).joinToString("；")
                windowsStatus = "ready"
            } catch (_: SSLException) {
                syncState = "failed"; syncStage = "同步失败"; syncDetail = "TLS 证书验证失败，请检查 PC 证书。"
            } catch (failure: Exception) {
                syncState = if (received + sent > 0) "partial" else "failed"
                syncStage = "同步未完成"; syncDetail = failure.message?.take(200) ?: "无法连接 PC，请检查网络后重试。"
            } finally {
                if (Files.exists(work)) Files.walk(work).use { paths -> paths.sorted(Comparator.reverseOrder()).forEach { Files.deleteIfExists(it) } }
                script("window.__fujimiRefreshNativeSettings?.()")
            }
        }
        return true
    }
    @JavascriptInterface fun resolveMediaUrl(value: String): String = if (value.startsWith("/api/")) "https://appassets.androidplatform.net$value" else ""
    @JavascriptInterface fun playMedia(url: String, position: Double, rate: Double): Boolean {
        speech.stop()
        return media.play(url, position, rate)
    }
    @JavascriptInterface fun mediaStatus(): String = media.status()
    @JavascriptInterface fun pauseMedia() { media.pause() }
    @JavascriptInterface fun seekMedia(position: Double) { media.seek(position) }
    @JavascriptInterface fun setMediaRate(rate: Double) { media.rate(rate) }
    @JavascriptInterface fun stopMedia() { media.stop() }
    @JavascriptInterface fun queueChange(entity: String, action: String, payload: String): String = ""

    @JavascriptInterface
    fun setServerUrl(value: String): Boolean {
        val normalized = try { if (value.isBlank()) "" else PcEndpoint.normalize(value) } catch (_: Exception) { return false }
        connectionGeneration.incrementAndGet()
        connection?.disconnect()
        val saved = preferences.edit().putString("server-url", normalized).commit()
        if (saved) {
            if (secrets.readPcPairing()?.optString("url") != normalized) {
                secrets.clearPcPairing()
                preferences.edit().putBoolean("pc-sync-available", false).commit()
            }
            windowsStatus = if (normalized.isEmpty()) "unconfigured" else "offline"
            connectionDetail = ""
            syncAvailable = false
        }
        return saved
    }

    @JavascriptInterface
    fun connectServer(value: String, callbackId: String) {
        val endpoint = try { PcEndpoint.normalize(value) } catch (_: Exception) {
            deliverSetup(callbackId, false, "请填写 PC 显示的局域网地址，例如 http://192.168.1.20:8429。")
            return
        }
        if (!setServerUrl(endpoint)) { deliverSetup(callbackId, false, "地址保存失败。"); return }
        val generation = connectionGeneration.get()
        windowsStatus = "checking"
        executor.execute {
            var success = false
            val detail = try {
                requireNetwork()
                val credentials = pairedCredentials()
                val info = PcSyncClient(endpoint, credentials?.optString("token").orEmpty())
                    .json(if (credentials == null) "/api/sync/v2/info" else "/api/sync/v2/status")
                require(info.optInt("protocol") == 2) { "节点协议不兼容，需更新 PC 协同版本。" }
                if (credentials == null) "PC 已连接，请输入配对码或扫描二维码。"
                else {
                    success = true
                    syncAvailable = info.optBoolean("sync_available")
                    preferences.edit().putBoolean("pc-sync-available", syncAvailable).commit()
                    "已连接 PC；点击立即同步传输文库。"
                }
            } catch (_: SSLException) { "TLS 证书验证失败，请检查 PC 证书及设备信任配置。" }
            catch (error: IllegalStateException) { error.message ?: "网络不可用。" }
            catch (_: Exception) { "无法连接 PC，请检查地址、网络和 PC 服务。地址已保存。" }
            if (connectionGeneration.get() != generation || closed) return@execute
            windowsStatus = if (success) "ready" else "offline"
            connectionDetail = detail
            deliverSetup(callbackId, success, detail)
        }
    }

    private fun pairedCredentials(): JSONObject? = secrets.readPcPairing()?.takeIf {
        it.optString("url") == preferences.getString("server-url", "")
    }

    @JavascriptInterface
    fun pairWindows(value: String, code: String, callbackId: String) {
        if (closed) return
        val pairing = try { PcPairing(PcEndpoint.normalize(value), PcPairing.validateCode(code)) }
        catch (failure: Exception) { deliverWindows(callbackId, false, failure.message ?: "地址或配对码无效。"); return }
        if (!setServerUrl(pairing.url)) { deliverWindows(callbackId, false, "地址保存失败。"); return }
        val generation = connectionGeneration.get()
        windowsStatus = "checking"
        executor.execute {
            var success = false
            val detail = try {
                requireNetwork()
                val deviceId = preferences.getString("sync-device-id", null) ?: UUID.randomUUID().toString().also {
                    check(preferences.edit().putString("sync-device-id", it).commit()) { "设备标识未能保存。" }
                }
                val reply = PcSyncClient(pairing.url).json("/api/sync/v2/pair", JSONObject()
                    .put("code", pairing.code).put("device_id", deviceId).put("device_name", Build.MODEL.take(100)))
                require(reply.optInt("protocol") == 2) { "PC 配对协议不兼容。" }
                if (generation != connectionGeneration.get() || closed) return@execute
                check(secrets.savePcPairing(pairing.url, reply.getString("token"), reply.getString("device_id"))) { "配对凭据未能安全保存，请重试。" }
                syncAvailable = reply.optBoolean("sync_available")
                preferences.edit().putBoolean("pc-sync-available", syncAvailable).commit()
                success = true
                "已配对 ${reply.optString("name", "Windows PC")}；点击立即同步传输文库。"
            } catch (_: SSLException) { "TLS 证书验证失败，请检查 PC 证书及设备信任配置。" }
            catch (failure: IllegalStateException) { failure.message ?: "配对失败，请检查 PC 服务。" }
            catch (failure: IllegalArgumentException) { failure.message ?: "配对信息无效。" }
            catch (_: Exception) { "无法连接 PC，请确认两台设备在同一网络且 PC 已开启同步。" }
            if (generation != connectionGeneration.get() || closed) return@execute
            windowsStatus = if (success) "ready" else "offline"
            connectionDetail = detail
            deliverWindows(callbackId, success, detail)
        }
    }

    @JavascriptInterface
    fun scanWindowsPairing(callbackId: String) {
        if (closed) return
        main.post {
            if (scanCallback != null) { deliverWindows(callbackId, false, "扫码已打开。"); return@post }
            scanCallback = callbackId
            try {
                IntentIntegrator(activity).setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
                    .setPrompt("扫描 PC 设置中的文庫同步二维码")
                    .setBeepEnabled(false).setOrientationLocked(false).setRequestCode(1003).initiateScan()
            } catch (_: Exception) { scanCallback = null; deliverWindows(callbackId, false, "无法打开相机，请检查相机权限。"); }
        }
    }

    fun completeWindowsScan(contents: String?) {
        val callbackId = scanCallback ?: return
        scanCallback = null
        if (contents == null) { deliverWindows(callbackId, false, "已取消扫码；也可输入地址和配对码连接。"); return }
        val pairing = try { PcPairing.parseQr(contents) }
        catch (_: Exception) { deliverWindows(callbackId, false, "二维码无效，请扫描 PC 设置中的文庫同步二维码。"); return }
        pairWindows(pairing.url, pairing.code, callbackId)
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
        media.stop()
        if (text.length > 200000) return deliverTts(utteranceId, "error")
        val generation = speechGeneration.incrementAndGet()
        executor.execute {
            if (generation != speechGeneration.get()) return@execute deliverTts(utteranceId, "stop")
            val selectedVoice = voiceName.ifEmpty { settings.value("voice-mode").optString("browser_voice_name", EdgeVoiceCatalog.KEITA) }
            if (selectedVoice !in setOf(EdgeVoiceCatalog.KEITA, EdgeVoiceCatalog.NANAMI) ||
                voiceName.isEmpty() && settings.value("voice-mode").optString("mode") == "voice") {
                deliverTts(utteranceId, "error")
                script("window.__fujimiNativeNotice?.('所选声线仅可播放从 PC 同步的完整音频；请先在 PC 生成后同步。')")
                return@execute
            }
            try { speech.speak(text, rate, utteranceId, selectedVoice) }
            catch (_: Exception) { deliverTts(utteranceId, "error") }
        }
    }
    @JavascriptInterface fun stopSpeaking() { speechGeneration.incrementAndGet(); speech.stop() }

    private fun script(value: String) { main.post { if (!closed) webView.evaluateJavascript(value, null) } }
    private fun deliver(id: String, code: Int, body: String) = script("window.__fujimiMobileResolve?.(${JSONObject.quote(id)},$code,${JSONObject.quote(body)})")
    private fun deliverTts(id: String, event: String) = script("window.__fujimiTtsEvent?.(${JSONObject.quote(id)},${JSONObject.quote(event)})")
    private fun deliverSetup(id: String, success: Boolean, detail: String) = script("window.__fujimiSetupResolve?.(${JSONObject.quote(id)},$success,${JSONObject.quote(detail)})")
    private fun deliverWindows(id: String, success: Boolean, detail: String) = script("window.__fujimiWindowsCheckResult?.(${JSONObject.quote(id)},$success,${JSONObject.quote(detail)})")

    fun close() {
        closed = true
        connectionGeneration.incrementAndGet()
        connection?.disconnect()
        executor.shutdownNow()
        speech.close()
        media.close()
        dictionary.close()
    }
}
