package jp.fujimi.newsbunko.next.settings

import jp.fujimi.newsbunko.next.store.ApiResponse
import jp.fujimi.newsbunko.next.store.LibrarySyncStore
import jp.fujimi.newsbunko.next.store.LocalVoiceStore
import org.json.JSONObject
import java.nio.file.Files
import java.nio.file.Path
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/** Paired PC synthesis followed by the existing delta transfer and local audio selection. */
class PcSpeechService(
    private val root: Path,
    private val credentials: () -> JSONObject?,
    private val prepareNetwork: (JSONObject) -> Unit,
    private val currentMode: () -> JSONObject,
    private val local: (String, String, String?) -> ApiResponse?,
    private val checkpoint: () -> Unit = {},
) {
    private data class Job(val pair: JSONObject, val kind: String, val id: Long, val chapter: Long,
        val selection: JSONObject, val key: String, val remoteId: String, var result: JSONObject? = null)
    private val jobs = ConcurrentHashMap<String, Job>()

    fun request(method: String, path: String, body: String?): ApiResponse? {
        if (!path.startsWith("/api/pc-speech/")) return null
        return try {
            val result = when {
                method == "POST" && path == "/api/pc-speech/start" -> start(JSONObject(body ?: "{}"))
                path.startsWith("/api/pc-speech/tasks/") && method in setOf("GET", "DELETE") -> {
                    val id = path.substringAfterLast('/')
                    val job = jobs[id] ?: throw IllegalArgumentException("PC 朗读任务已失效，请重试。")
                    synchronized(job) {
                        checkPair(job.pair, method != "DELETE")
                        if (method == "GET" && job.result != null) job.result!!
                        else {
                            val value = client(job.pair).json("/api/sync/v2/tts/tasks/${job.remoteId}", method = method)
                            if (method == "GET" && value.optString("status") in setOf("completed", "ready")) finish(job) else value
                        }
                    }
                }
                else -> throw IllegalArgumentException("朗读请求无效。")
            }
            ApiResponse(200, result.toString())
        } catch (failure: Exception) {
            val message = when (failure) {
                is java.net.SocketTimeoutException -> "PC 响应超时，请检查文库互连后重试。"
                is java.net.ConnectException, is java.net.UnknownHostException -> "无法连接 PC，请确认电脑文庫与互连已开启。"
                else -> failure.message?.take(500) ?: "PC 朗读失败，请重试。"
            }
            ApiResponse(502, JSONObject().put("detail", message).toString())
        }
    }

    private fun start(body: JSONObject): JSONObject {
        val pair = credentials() ?: error("请先连接并配对 PC。")
        prepareNetwork(pair)
        val client = client(pair)
        val info = client.json("/api/sync/v2/status")
        check(info.optBoolean("speech_available")) { "请先更新 PC 客户端，启用手机发起朗读。" }
        val kind = body.getString("kind"); require(kind in setOf("article", "book"))
        val id = body.getLong("id")
        val chapter = body.optLong("chapter_id")
        var selection = body.getJSONObject("selection")
        if (selection.optString("mode") in setOf("model", "inherit")) selection = currentMode()
        if (selection.optString("mode") == "browser" && selection.optString("browser_voice_name").isEmpty())
            selection.put("browser_voice_name", currentMode().optString("browser_voice_name"))
        val store = LibrarySyncStore(root)
        val item = store.speechItem(kind, id)
        val remote = client.json("/api/sync/v2/manifest").getJSONArray("items")
        val remoteItems = (0 until remote.length()).map { remote.getJSONObject(it) }.associateBy { it.getString("key") }
        val work = root.resolve("diagnostics/pc-speech/${UUID.randomUUID()}")
        Files.createDirectories(work)
        try {
            fun supplement(value: JSONObject) {
                val existing = remoteItems[value.getString("key")]
                if (!LibrarySyncStore.needsTransfer(value, existing)) return
                val bundle = work.resolve("upload.zip")
                store.exportBundle(value.getString("key"), bundle, existing?.optJSONObject("files") ?: JSONObject())
                checkPair(pair); client.upload(bundle); Files.deleteIfExists(bundle)
            }
            supplement(item)
            val request = JSONObject().put("key", item.getString("key")).put("mode", selection.getString("mode"))
            if (kind == "book") request.put("chapter_id", chapter)
            when (selection.getString("mode")) {
                "voice" -> {
                    val voice = LocalVoiceStore(root).find(selection.getLong("voice_id")) ?: error("所选参考声线不存在。")
                    val name = voice.getString("name")
                    supplement(store.speechItem("voice", name = name))
                    request.put("voice_name", name)
                }
                "browser" -> request.put("browser_voice_name", selection.getString("browser_voice_name"))
                else -> error("请先选择朗读声线。")
            }
            checkPair(pair)
            val reply = client.json("/api/sync/v2/tts/start", request)
            val job = Job(pair, kind, id, chapter, selection, item.getString("key"), reply.optString("task_id"))
            if (reply.optString("status") in setOf("ready", "completed")) return finish(job)
            check(job.remoteId.isNotEmpty()) { "PC 未返回朗读任务。" }
            val localId = UUID.randomUUID().toString(); jobs[localId] = job
            return reply.put("task_id", localId)
        } finally { removeWork(work) }
    }

    private fun finish(job: Job): JSONObject {
        checkPair(job.pair)
        val store = LibrarySyncStore(root)
        val item = store.speechItem(job.kind, job.id)
        val work = root.resolve("diagnostics/pc-speech/${UUID.randomUUID()}")
        Files.createDirectories(work)
        try {
            val bundle = work.resolve("audio.zip")
            client(job.pair).download(job.key, bundle, item.getJSONObject("files"))
            checkPair(job.pair); store.importBundle(bundle)
            val route = if (job.kind == "article") "/api/articles/${job.id}/reread"
                else "/api/books/${job.id}/chapters/${job.chapter}/reread"
            val selected = local("POST", route, job.selection.toString()) ?: error("手机朗读接口不可用。")
            val result = JSONObject(selected.body)
            check(selected.status == 200 && result.optString("status") == "ready") {
                result.optString("detail", "PC 音频尚未完整接收，请重试。")
            }
            job.result = result
            return result
        } finally { removeWork(work) }
    }

    private fun checkPair(pair: JSONObject, active: Boolean = true) {
        if (active) checkpoint()
        val now = credentials()
        check(now != null && now.optString("url") == pair.optString("url") && now.optString("token") == pair.optString("token")) { "PC 连接已变更，请重新开始朗读。" }
    }
    private fun client(pair: JSONObject) = PcSyncClient(pair.getString("url"), pair.getString("token"))
    private fun removeWork(path: Path) {
        if (Files.exists(path)) Files.walk(path).use { it.sorted(Comparator.reverseOrder()).forEach { file -> Files.deleteIfExists(file) } }
    }
}
