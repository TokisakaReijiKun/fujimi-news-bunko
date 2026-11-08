package jp.fujimi.newsbunko.next.daily

import android.content.Context
import jp.fujimi.newsbunko.next.settings.PcSpeechService
import jp.fujimi.newsbunko.next.settings.PcSyncClient
import jp.fujimi.newsbunko.next.settings.SecretStore
import jp.fujimi.newsbunko.next.speech.EdgeSpeechPlayer
import jp.fujimi.newsbunko.next.speech.ArticleEdgeAudio
import jp.fujimi.newsbunko.next.store.LibrarySyncStore
import jp.fujimi.newsbunko.next.store.LocalLibraryApi
import org.json.JSONObject
import java.nio.file.Files
import java.nio.file.Path

/** Reuses interactive PC speech and the phone's full-file Edge synthesis. */
internal class DailySpeech(private val context: Context, private val root: Path,
                           articles: List<JSONObject>, selection: JSONObject, private val checkpoint: () -> Unit) {
    private val preferences = context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE)
    private val secrets = SecretStore(context)
    private fun credentials() = secrets.readPcPairing()?.takeIf { it.optString("url") == preferences.getString("server-url", "") }
    private val pair = credentials()?.takeIf { pair ->
        runCatching {
            PcSyncClient(pair.getString("url"), pair.getString("token"), 2500).json("/api/sync/v2/status")
            true
        }.getOrDefault(false)
    }
    val queue = DailySpeechQueue(articles, selection, pair != null)
    private val library = LocalLibraryApi(root, voiceSettings = { selection })
    @Volatile private var activeTask: String? = null
    private val remote = PcSpeechService(root, ::credentials, { PublicHttpClient.requireNetwork(context) }, { selection },
        library::request, checkpoint)

    fun advance(): Boolean = queue.advance({ id, selected, task ->
        val reply = if (task == null) remote.request("POST", "/api/pc-speech/start", JSONObject()
            .put("kind", "article").put("id", id).put("selection", selected).toString())
        else remote.request("GET", "/api/pc-speech/tasks/$task", null)
        check(reply != null) { "PC 朗读接口不可用。" }
        val value = JSONObject(reply.body)
        activeTask = task ?: value.optString("task_id").takeIf { it.isNotEmpty() }
        checkpoint()
        check(reply.status in 200..299) { value.optString("detail", "PC 朗读失败。") }
        // Poll responses carry the remote ID; this service owns the local ID returned at start.
        if (task != null) value.put("task_id", task)
        if (value.optString("status") in setOf("ready", "completed", "failed", "cancelled")) activeTask = null
        value
    }, { id, voice ->
        val player = EdgeSpeechPlayer(context) { _, _ -> }
        try {
            ArticleEdgeAudio(root, { paragraphs, name ->
                checkpoint(); player.completeArticle(paragraphs, name).also { checkpoint() }
            }, { file -> player.validateFile(file); checkpoint() }).generate(id, voice)
        } finally { player.close() }
    }, ::upload, checkpoint)

    private fun upload(id: Long) {
        val pair = pair ?: return
        checkpoint()
        val client = PcSyncClient(pair.getString("url"), pair.getString("token"))
        val store = LibrarySyncStore(root)
        val item = store.speechItem("article", id)
        val manifest = client.json("/api/sync/v2/manifest").getJSONArray("items")
        val existing = (0 until manifest.length()).map { manifest.getJSONObject(it) }.firstOrNull { it.optString("key") == item.getString("key") }
        if (!LibrarySyncStore.needsTransfer(item, existing)) return
        val work = root.resolve("diagnostics/pc-speech")
        Files.createDirectories(work)
        val bundle = Files.createTempFile(work, "daily-", ".zip")
        try {
            store.exportBundle(item.getString("key"), bundle, existing?.optJSONObject("files") ?: JSONObject())
            checkpoint()
            val now = credentials()
            check(now != null && now.optString("url") == pair.optString("url") && now.optString("token") == pair.optString("token")) { "PC 连接已变更。" }
            client.upload(bundle)
        } finally { Files.deleteIfExists(bundle) }
    }

    fun cancel() {
        val task = activeTask ?: queue.pendingTask() ?: return
        remote.request("DELETE", "/api/pc-speech/tasks/$task", null)
    }
}
