package jp.fujimi.newsbunko.next.daily

import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CancellationException

/** One selected voice for this edition; complete files always retain their actual voice. */
class DailySpeechQueue(articles: List<JSONObject>, selection: JSONObject, private val paired: Boolean) {
    private val articles = articles.filter { it.optString("source_voice_mode") != "none" && selection.optString("mode") != "none" }
    private val selection = JSONObject(selection.toString())
    private var position = 0
    private var task: String? = null
    private var successful = 0
    val errors = JSONArray()
    val finished get() = position == articles.size
    private val nativeVoice = selection.optString("browser_voice_name").takeIf {
        selection.optString("mode") == "browser" && it in setOf(EdgeVoiceCatalog.KEITA, EdgeVoiceCatalog.NANAMI)
    }
    val usesPc get() = paired && nativeVoice == null
    val fallback get() = !paired && nativeVoice == null && articles.isNotEmpty()

    /** False means a PC job is pending; call again without starting a second job. */
    fun advance(remote: (Long, JSONObject, String?) -> JSONObject, phone: (Long, String) -> Unit,
                upload: (Long) -> Unit, checkpoint: () -> Unit): Boolean {
        checkpoint()
        if (finished) return true
        val article = articles[position]
        val id = article.getLong("id")
        try {
            if (usesPc) {
                val reply = remote(id, JSONObject(selection.toString()), task)
                checkpoint()
                when (reply.optString("status")) {
                    "ready", "completed" -> task = null
                    "failed", "cancelled", "interrupted" -> error(reply.optString("detail").ifEmpty { reply.optString("message", "PC 朗读失败。") })
                    else -> {
                        task = reply.optString("task_id").takeIf { it.isNotEmpty() } ?: task
                        check(task != null) { "PC 未返回朗读任务。" }
                        return false
                    }
                }
            } else {
                phone(id, nativeVoice ?: EdgeVoiceCatalog.KEITA)
                checkpoint()
                if (paired) upload(id)
                checkpoint()
            }
            successful++
        } catch (cancelled: CancellationException) { throw cancelled }
        catch (failure: Exception) {
            checkpoint()
            errors.put("${article.optString("title")}: ${failure.message ?: "朗读音频生成失败。"}")
        }
        task = null
        position++
        return true
    }

    fun progress(): JSONObject = JSONObject().put("audio_completed", successful).put("audio_total", articles.size)
        .put("stage", "speech").put("status", "running").put("percent", 99)
        .put("message", when {
            finished -> "朗读音频处理完成（$successful/${articles.size}）。"
            usesPc -> "PC 正在生成并回传朗读音频（$position/${articles.size}）。"
            fallback -> "PC 未连接，使用圭太生成朗读音频（$position/${articles.size}）。"
            else -> "正在生成朗读音频（$position/${articles.size}）。"
        })

    fun pendingTask(): String? = task
}
