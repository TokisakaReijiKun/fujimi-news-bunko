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
import jp.fujimi.newsbunko.next.settings.PcSpeechService
import jp.fujimi.newsbunko.next.settings.SecretStore
import jp.fujimi.newsbunko.next.settings.TailscaleAccess
import jp.fujimi.newsbunko.next.settings.SettingsBackend
import jp.fujimi.newsbunko.next.speech.EdgeSpeechPlayer
import jp.fujimi.newsbunko.next.speech.SystemSpeechPlayer
import jp.fujimi.newsbunko.next.daily.PublicHttpClient
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
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.SSLException
import com.google.zxing.integration.android.IntentIntegrator
import java.util.UUID
import java.nio.file.Files
import java.nio.file.Path

class MobileBridge(private val activity: Activity, private val webView: WebView) {
    @JavascriptInterface fun openMojiDictionary(word: String): Boolean {
        if (word.isBlank() || word.length > 100) return false
        val uri = Uri.Builder().scheme("mojisho").authority("mojidict.com").appendQueryParameter("search", word).build()
        return try {
            activity.startActivity(Intent(Intent.ACTION_VIEW, uri).setPackage("com.mojitec.mojidict"))
            true
        } catch (_: android.content.ActivityNotFoundException) { false }
        catch (_: SecurityException) { false }
    }
    private val context = activity.applicationContext
    private val preferences = context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE)
    private val executor = Executors.newFixedThreadPool(2)
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var voicePickerCallback: String? = null
    @Volatile private var voiceUpload: Pair<String, Path>? = null
    private val dataRoot = DataDirectory.prepare(context)
    private val daily = DailyRuntime.get(context)
    private val library by lazy { LocalLibraryApi(dataRoot.toPath(), daily::snapshot, { settings.value("voice-mode") }, settings::browserVoices) }
    private val syncedLibrary by lazy { jp.fujimi.newsbunko.next.store.LocalSyncedLibraryApi(dataRoot.toPath(), { settings.value("voice-mode") }, settings::browserVoices) }
    private val dictionary = DictionaryRepository(context)
    private val secrets = SecretStore(context)
    private val speech = EdgeSpeechPlayer(context) { id, event -> deliverTts(id, event) }
    private val systemSpeech = SystemSpeechPlayer(context) { id, event -> deliverTts(id, event) }
    private val articleAudio = ArticleEdgeAudio(dataRoot.toPath(), speech::completeArticle, speech::validateFile)
    private val media = ArticleMediaPlayer(context, dataRoot.toPath())
    private val settings = LocalSettingsApi(object : SettingsBackend {
        override fun read(key: String) = preferences.getString("setting:$key", null)
        override fun write(key: String, value: String) {
            check(preferences.edit().putString("setting:$key", value).commit()) { "设置保存失败，请检查可用空间。" }
        }
    }, daily.schedule, LocalVoiceStore(dataRoot.toPath())) {
        org.json.JSONArray().put(systemSpeech.voice()).apply {
            val online = EdgeVoiceCatalog.voices()
            for (index in 0 until online.length()) put(online.getJSONObject(index))
        }
    }
    private val connectionGeneration = AtomicLong()
    private val tailscale = TailscaleAccess(activity)
    private val pcSpeech by lazy { PcSpeechService(dataRoot.toPath(), ::pairedCredentials, { pair ->
        requireNetwork()
        val generation = connectionGeneration.get()
        tailscale.awaitReady(pair.getString("url"), { !closed && generation == connectionGeneration.get() }) {
            script("window.__fujimiNativeNotice?.('接続のためTailscaleを開きます。',false)")
        }
        check(!closed && generation == connectionGeneration.get()) { "PC 连接已变更。" }
    }, { settings.value("voice-mode") }, { method, route, body ->
        syncedLibrary.request(method, route, body) ?: library.request(method, route, body)
    }) }
    private val speechGeneration = AtomicLong()
    @Volatile private var closed = false
    @Volatile private var windowsStatus = if (preferences.getString("server-url", "").isNullOrEmpty()) "unconfigured" else "offline"
    @Volatile private var connectionDetail = ""
    private val connectionProbeBusy = AtomicBoolean(false)
    @Volatile private var connectionProbed = false
    @Volatile private var connection: HttpURLConnection? = null
    @Volatile private var scanCallback: String? = null
    @Volatile private var syncAvailable = preferences.getBoolean("pc-sync-available", false)
    @Volatile private var pcSpeechAvailable = false
    @Volatile private var pcSpeechModelAvailable = false
    @Volatile private var syncState = "idle"
    @Volatile private var syncStage = "尚未同步"
    @Volatile private var syncDetail = "配对后点击立即同步，双向补齐文库内容。"
    @Volatile private var syncProgress = 0

    @JavascriptInterface
    fun request(payload: String, callbackId: String) {
        if (closed) return
        if (payload.length > 1024 * 1024) return deliver(callbackId, 413, JSONObject().put("detail", "请求过大，请使用原生文件导入。").toString())
        executor.execute {
            var upload: Path? = null
            val result = try {
                val request = JSONObject(payload)
                val method = request.optString("method", "GET")
                val path = request.getString("path")
                require(path.startsWith("/api/") && !path.contains('#'))
                val body = if (request.isNull("body")) null else request.optString("body")
                if (path == "/api/settings/voice-file") {
                    if (method == "POST") {
                        val audioUrl = body?.let { JSONObject(it).optString("audio_url") }.orEmpty().trim()
                        if (audioUrl.isEmpty()) pickVoiceFile(callbackId) else downloadVoiceFile(audioUrl, callbackId)
                        return@execute
                    }
                    if (method == "DELETE") {
                        if (body?.let { JSONObject(it).optString("file_token") } == voiceUpload?.first) clearVoiceUpload()
                        deliver(callbackId, 200, "{\"ok\":true}"); return@execute
                    }
                }
                val token = body?.let { JSONObject(it).optString("file_token") }.orEmpty()
                if (token.isNotEmpty()) {
                    require(method in setOf("POST", "PUT") && (Regex("/api/settings/voices(?:/\\d+)?").matches(path) || path == "/api/settings/browser-voices"))
                    upload = voiceUpload?.takeIf { it.first == token }?.second ?: error("所选音频已失效，请重新选择。")
                }
                when (path.substringBefore('?')) {
                    "/api/health" -> ApiResponse(200, JSONObject().put("status", "ok").put("runtime", "android")
                        .put("dictionary", true).put("translation_configured", secrets.isConfigured())
                        .put("tts", "browser").put("tts_details", JSONObject().put("enabled", false))
                        .put("capabilities", JSONObject().put("system_speech", systemSpeech.voice().getBoolean("available")).put("edge_speech", true).put("sync", true).put("daily_generation", true).put("reference_voices", true).put("reference_synthesis", false)).toString())
                    else -> pcSpeech.request(method, path, body) ?: edgeAudioRequest(method, path, body) ?: daily.request(method, path) ?: settings.request(method, path, body, upload) ?: dictionary.request(method, path, body) ?: syncedLibrary.request(method, path, body) ?: library.request(method, path, body)
                }
            } catch (_: Exception) {
                ApiResponse(400, JSONObject().put("detail", "请求或设置未能保存，请检查格式与可用空间。").toString())
            }
            if (upload != null && result.status in 200..299) clearVoiceUpload()
            deliver(callbackId, result.status, result.body)
        }
    }

    @Synchronized private fun clearVoiceUpload() {
        voiceUpload?.second?.let { Files.deleteIfExists(it) }
        voiceUpload = null
    }

    private fun downloadVoiceFile(url: String, callback: String) {
        val transport = PublicHttpClient(context) { check(!closed) }
        var file: Path? = null
        try {
            require(url.length <= 4096)
            val download = transport.download(url, 20 * 1024 * 1024)
            file = Files.createTempFile(context.cacheDir.toPath(), "voice-url-", ".wav")
            Files.write(file, download.bytes)
            val duration = LocalVoiceStore.validate(file)
            val token = UUID.randomUUID().toString()
            synchronized(this) { clearVoiceUpload(); voiceUpload = token to file }
            file = null
            val filename = Uri.parse(download.url).lastPathSegment?.takeIf { it.endsWith(".wav", true) } ?: "音声.wav"
            deliver(callback, 200, JSONObject().put("file_token", token).put("filename", filename).put("duration", duration).toString())
        } catch (_: Exception) {
            file?.let { Files.deleteIfExists(it) }
            deliver(callback, 400, "{\"detail\":\"音声URLを読み込めません。公開HTTPSのWAVファイル（1–120秒、20 MiB以下）を確認してください。\"}")
        } finally {
            transport.client.dispatcher.executorService.shutdown()
            transport.client.connectionPool.evictAll()
        }
    }

    @Synchronized private fun pickVoiceFile(callback: String) {
        if (voicePickerCallback != null) { deliver(callback, 409, "{\"detail\":\"请先完成当前文件选择。\"}"); return }
        voicePickerCallback = callback
        main.post {
            try { activity.startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("audio/*"), 1004) }
            catch (_: android.content.ActivityNotFoundException) {
                voicePickerCallback = null; deliver(callback, 503, "{\"detail\":\"无法打开系统文件选择器。\"}")
            }
        }
    }

    fun completeVoiceFileSelection(uri: Uri?) {
        val callback = voicePickerCallback ?: return
        if (uri == null) { voicePickerCallback = null; deliver(callback, 200, "{\"cancelled\":true}"); return }
        executor.execute {
            clearVoiceUpload()
            val file = context.cacheDir.toPath().resolve("voice-import.wav")
            try {
                context.contentResolver.openInputStream(uri).use { input ->
                    requireNotNull(input)
                    Files.newOutputStream(file).use { output ->
                        val buffer = ByteArray(65536); var total = 0L
                        while (true) {
                            val count = input.read(buffer); if (count < 0) break
                            total += count; require(total <= 20L * 1024 * 1024) { "声线音频须小于 20 MiB。" }
                            output.write(buffer, 0, count)
                        }
                    }
                }
                val duration = LocalVoiceStore.validate(file)
                val filename = context.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
                    if (it.moveToFirst()) it.getString(0) else null
                } ?: "音频.wav"
                val token = UUID.randomUUID().toString()
                voiceUpload = token to file
                deliver(callback, 200, JSONObject().put("file_token", token).put("filename", filename).put("duration", duration).toString())
            } catch (failure: Exception) {
                Files.deleteIfExists(file)
                deliver(callback, 400, JSONObject().put("detail", failure.message ?: "请选择有效的 WAV 文件。").toString())
            } finally { voicePickerCallback = null }
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
        .put("reference_synthesis_available", pairedCredentials() != null && windowsStatus == "ready" && pcSpeechModelAvailable)
        .put("pc_speech_available", pairedCredentials() != null && windowsStatus == "ready" && pcSpeechAvailable)
        .put("saved_audio_voices_available", true)
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
                tailscale.awaitReady(credentials.getString("url"), { !closed && generation == connectionGeneration.get() }) {
                    syncStage = "Tailscaleを待機中"; syncDetail = "接続後に文庫へ戻ってください。"
                    script("window.__fujimiNativeNotice?.('Tailscaleを開きます。接続後に文庫へ戻ってください。',false)")
                }
                syncStage = "读取文库清单"; syncDetail = "正在检查 PC 连接。"
                requireNetwork(); checkpoint()
                Files.createDirectories(work)
                val client = PcSyncClient(credentials.getString("url"), credentials.getString("token"))
                val info = client.json("/api/sync/v2/status")
                check(info.optInt("protocol") == 2 && info.optBoolean("sync_available")) { "PC 尚未开启文库同步。" }
                windowsStatus = "ready"
                connectionDetail = "已连接 PC。"
                val store = LibrarySyncStore(dataRoot.toPath())
                val local = store.manifest()
                val remote = client.json("/api/sync/v2/manifest")
                require(remote.optInt("version") == 1) { "PC 文库清单版本不兼容。" }
                require(remote.optString("file_comparison") == "path-size-v1") { "请先更新 PC 客户端，以使用按路径和大小同步。" }
                remote.optJSONArray("browser_voices")?.let(settings::savePcBrowserVoices)
                for (list in listOf(local.optJSONArray("errors"), remote.optJSONArray("errors"))) {
                    if (list != null) for (i in 0 until list.length()) errors += list.opt(i).toString().take(180)
                }
                fun items(value: JSONObject): List<JSONObject> = value.getJSONArray("items").let { list ->
                    (0 until list.length()).map { list.getJSONObject(it) }
                }
                val localItems = items(local).associateBy { it.getString("key") }
                val remoteItems = items(remote).associateBy { it.getString("key") }
                fun knownFilesFor(source: JSONObject, target: JSONObject?): JSONObject {
                    val known = JSONObject((target?.optJSONObject("files") ?: JSONObject()).toString())
                    val features = source.optJSONObject("chapter_features") ?: return known
                    val targetFeatures = target?.optJSONObject("chapter_features") ?: return known
                    for (name in features.keys()) {
                        val offered = features.getJSONArray(name)
                        val present = targetFeatures.optJSONArray(name) ?: continue
                        val existing = (0 until present.length()).map { present.getString(it) }.toSet()
                        if ((0 until offered.length()).any { offered.getString(it) !in existing }) known.remove(name)
                    }
                    return known
                }
                val downloads = remoteItems.values.filter { LibrarySyncStore.needsTransfer(it, localItems[it.getString("key")]) }
                val uploads = localItems.values.filter { LibrarySyncStore.needsTransfer(it, remoteItems[it.getString("key")]) }
                val total = downloads.size + uploads.size
                for (item in downloads) {
                    checkpoint()
                    syncStage = "接收 PC 文库"; syncDetail = item.optString("title")
                    val bundle = work.resolve("download.zip")
                    try {
                        client.download(item.getString("key"), bundle, knownFilesFor(item, localItems[item.getString("key")])); checkpoint()
                        val result = store.importBundle(bundle)
                        if (result.getString("status") == "conflict") errors += "${item.optString("title")}：正文或附件冲突，已保留本机内容。"
                        else if (result.getString("status") != "unchanged") received++
                    } catch (failure: Exception) {
                        android.util.Log.w("FujimiSync", "PC bundle receive/import failed", failure)
                        if (failure is java.io.IOException) { windowsStatus = "offline"; syncAvailable = false }
                        errors += "${item.optString("title")}：${failure.message?.take(160) ?: "接收失败"}"
                    }
                    finally { Files.deleteIfExists(bundle) }
                    completed++; syncProgress = if (total == 0) 0 else (completed * 99 / total)
                }
                for (item in uploads) {
                    checkpoint()
                    syncStage = "发送手机文库"; syncDetail = item.optString("title")
                    val bundle = work.resolve("upload.zip")
                    try {
                        store.exportBundle(item.getString("key"), bundle, knownFilesFor(item, remoteItems[item.getString("key")])); checkpoint()
                        val result = client.upload(bundle)
                        if (result.optString("status") == "conflict") errors += "${item.optString("title")}：PC 已有不同内容，未覆盖。"
                        else if (result.optString("status") in setOf("created", "updated")) sent++
                    } catch (failure: Exception) {
                        if (failure is java.io.IOException) { windowsStatus = "offline"; syncAvailable = false }
                        errors += "${item.optString("title")}：${failure.message?.take(160) ?: "发送失败"}"
                    }
                    finally { Files.deleteIfExists(bundle) }
                    completed++; syncProgress = if (total == 0) 0 else (completed * 99 / total)
                }
                checkpoint()
                syncState = if (errors.isEmpty()) "completed" else "partial"
                syncStage = if (errors.isEmpty()) "同步完成" else "部分同步完成"
                syncProgress = if (errors.isEmpty()) 100 else 99
                syncDetail = "接收 $received 项，发送 $sent 项。" + if (errors.isEmpty()) "文库已核对。" else errors.take(3).joinToString("；")
            } catch (_: SSLException) {
                if (generation == connectionGeneration.get() && !closed) {
                    windowsStatus = "offline"; syncAvailable = false
                    connectionDetail = "TLS 证书验证失败，请检查 PC 证书。"
                }
                syncState = "failed"; syncStage = "同步失败"; syncDetail = "TLS 证书验证失败，请检查 PC 证书。"
            } catch (failure: Exception) {
                if (failure is java.io.IOException && generation == connectionGeneration.get() && !closed) {
                    windowsStatus = "offline"; syncAvailable = false
                    connectionDetail = "无法连接 PC，请检查网络和 PC 服务。"
                }
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
        tailscale.cancel()
        connection?.disconnect()
        val saved = preferences.edit().putString("server-url", normalized).commit()
        if (saved) {
            if (secrets.readPcPairing()?.optString("url") != normalized) {
                secrets.clearPcPairing()
                preferences.edit().putBoolean("pc-sync-available", false).commit()
            }
            windowsStatus = if (normalized.isEmpty()) "unconfigured" else "offline"
            connectionProbed = false
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
                    pcSpeechAvailable = info.optBoolean("speech_available")
                    pcSpeechModelAvailable = info.optBoolean("speech_model_available")
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

    /** A foreground status probe never changes pairing or launches another app. */
    @JavascriptInterface
    fun refreshWindowsConnection() {
        if (closed) return
        val generation = connectionGeneration.get()
        val credentials = pairedCredentials() ?: return
        if (!connectionProbeBusy.compareAndSet(false, true)) return
        if (!connectionProbed && windowsStatus != "ready") windowsStatus = "checking"
        executor.execute {
            var connected = false
            var available = false
            var remoteSpeech = false
            var remoteModelSpeech = false
            val detail = try {
                requireNetwork()
                val info = PcSyncClient(credentials.getString("url"), credentials.getString("token"), 2000)
                    .json("/api/sync/v2/status")
                require(info.optInt("protocol") == 2) { "PC 协同版本不兼容。" }
                connected = true
                available = info.optBoolean("sync_available")
                remoteSpeech = info.optBoolean("speech_available")
                remoteModelSpeech = info.optBoolean("speech_model_available")
                if (available) "已连接 PC。" else "PC 已连接，文库同步尚未开启。"
            } catch (_: SSLException) { "TLS 证书验证失败，请检查 PC 证书。" }
            catch (_: Exception) { "无法连接 PC，请检查网络和 PC 服务。" }
            try {
                if (!closed && generation == connectionGeneration.get()) {
                    windowsStatus = if (connected) "ready" else "offline"
                    syncAvailable = available
                    pcSpeechAvailable = remoteSpeech
                    pcSpeechModelAvailable = remoteModelSpeech
                    connectionDetail = detail
                    connectionProbed = true
                }
            } finally { connectionProbeBusy.set(false) }
        }
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
                tailscale.awaitReady(pairing.url, { !closed && generation == connectionGeneration.get() }) {
                    script("window.__fujimiWindowsCheckPhase?.(${JSONObject.quote(callbackId)},'tailscale')")
                }
                if (generation != connectionGeneration.get() || closed) return@execute
                script("window.__fujimiWindowsCheckPhase?.(${JSONObject.quote(callbackId)},'connecting')")
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
                pcSpeechAvailable = reply.optBoolean("speech_available")
                pcSpeechModelAvailable = reply.optBoolean("speech_model_available")
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
            if (voiceName.isEmpty() && settings.value("voice-mode").optString("mode") == "none") {
                deliverTts(utteranceId, "error")
                script("window.__fujimiNativeNotice?.('请先选择声线。')")
                return@execute
            }
            if (selectedVoice == SystemSpeechPlayer.ID &&
                (voiceName.isNotEmpty() || settings.value("voice-mode").optString("mode") == "browser")) {
                speech.stop()
                try { systemSpeech.speak(text, rate, utteranceId) { closed || generation != speechGeneration.get() } }
                catch (_: Exception) {
                    deliverTts(utteranceId, "error")
                    script("window.__fujimiNativeNotice?.('手机的文字转语音引擎尚未提供日语音声，请在系统设置中启用。')")
                }
                return@execute
            }
            if (selectedVoice !in setOf(EdgeVoiceCatalog.KEITA, EdgeVoiceCatalog.NANAMI) ||
                voiceName.isEmpty() && settings.value("voice-mode").optString("mode") == "voice") {
                deliverTts(utteranceId, "error")
                script("window.__fujimiNativeNotice?.('所选声线仅可播放从 PC 同步的完整音频；请先在 PC 生成后同步。')")
                return@execute
            }
            systemSpeech.stop()
            try { speech.speak(text, rate, utteranceId, selectedVoice) }
            catch (_: Exception) { deliverTts(utteranceId, "error") }
        }
    }
    @JavascriptInterface fun stopSpeaking() { speechGeneration.incrementAndGet(); speech.stop(); systemSpeech.stop() }

    private fun script(value: String) { main.post { if (!closed) webView.evaluateJavascript(value, null) } }
    private fun deliver(id: String, code: Int, body: String) = script("window.__fujimiMobileResolve?.(${JSONObject.quote(id)},$code,${JSONObject.quote(body)})")
    private fun deliverTts(id: String, event: String) = script("window.__fujimiTtsEvent?.(${JSONObject.quote(id)},${JSONObject.quote(event)})")
    private fun deliverSetup(id: String, success: Boolean, detail: String) = script("window.__fujimiSetupResolve?.(${JSONObject.quote(id)},$success,${JSONObject.quote(detail)})")
    private fun deliverWindows(id: String, success: Boolean, detail: String) = script("window.__fujimiWindowsCheckResult?.(${JSONObject.quote(id)},$success,${JSONObject.quote(detail)})")

    fun onPause() = tailscale.onPause()
    fun onResume() = tailscale.onResume()

    fun close() {
        closed = true
        connectionGeneration.incrementAndGet()
        tailscale.cancel()
        connection?.disconnect()
        executor.shutdownNow()
        clearVoiceUpload()
        speech.close()
        systemSpeech.close()
        media.close()
        dictionary.close()
    }
}
