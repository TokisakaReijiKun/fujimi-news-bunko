package jp.fujimi.newsbunko.next.daily

import android.content.Context
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import jp.fujimi.newsbunko.next.news.NewsProviders
import jp.fujimi.newsbunko.next.settings.CstSchedule
import jp.fujimi.newsbunko.next.store.ApiResponse
import jp.fujimi.newsbunko.next.storage.DataDirectory
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.CancellationException
import java.util.concurrent.TimeUnit

/** Survives Activity destruction. Task identity is unrelated to content filenames. */
class DailyRuntime private constructor(private val context: Context) {
    private val preferences = context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE)
    private val tasks = context.getSharedPreferences("daily-tasks", Context.MODE_PRIVATE)
    private val lock = Any()
    private val dataRoot = DataDirectory.root()
    private val index = AndroidArticleIndex(dataRoot)
    val schedule = AndroidDailySchedule(context)
    init {
        val previous = snapshot()
        if (previous.optString("status") == "running") {
            previous.put("status", "interrupted").put("stage", "interrupted").put("message", "上次任务随进程中断；已保存文章保留，请手动重试。")
            save(previous)
        }
        try { DataDirectory.prepare(context); jp.fujimi.newsbunko.next.store.ArticleStore(dataRoot.toPath()).recover(); index.rebuild() }
        catch (_: Exception) { preferences.edit().putString("article-index-error", "文库文件或索引需要检查；未从数据库恢复旧正文。").commit() }
    }

    fun request(method: String, path: String): ApiResponse? = when {
        path == "/api/daily/generate" && method == "POST" -> start().let { ApiResponse(if (it.optString("status") == "failed") 503 else 202, it.toString()) }
        path == "/api/tasks/daily" && method == "GET" -> ApiResponse(200, snapshot().toString())
        path == "/api/tasks/daily" && method == "DELETE" -> ApiResponse(200, cancel().toString())
        else -> null
    }

    fun start(date: String = LocalDate.now(CstSchedule.zone).toString(), expected: Long = 0, generation: String? = null): JSONObject = synchronized(lock) {
        LocalDate.parse(date)
        val current = snapshot()
        if (current.optString("status") == "running") return@synchronized JSONObject().put("status", "already_running")
        try { DataDirectory.prepare(context) }
        catch (failure: Exception) { return@synchronized JSONObject().put("status", "failed").put("detail", failure.message) }
        val token = UUID.randomUUID().toString()
        val job = OneTimeWorkRequestBuilder<DailyWorker>()
            .setInputData(workDataOf("token" to token, "date" to date, "expected" to expected, "scheduleGeneration" to (generation ?: "")))
            .addTag("fujimi-daily").build()
        save(JSONObject().put("id", token).put("work_id", job.id.toString()).put("status", "running").put("stage", "starting")
            .put("date", date).put("percent", 0).put("total", 0).put("completed", 0)
            .put("message", "日刊任务已排队，等待系统执行。").put("errors", JSONArray()).put("candidate_stats", JSONObject()))
        try {
            WorkManager.getInstance(context).enqueueUniqueWork("fujimi-daily-$token", ExistingWorkPolicy.KEEP, job).result.get(10, TimeUnit.SECONDS)
        } catch (_: Exception) {
            update(token, JSONObject().put("status", "failed").put("stage", "failed").put("message", "后台任务未能启动。"))
            return@synchronized JSONObject().put("status", "failed").put("detail", "后台任务未能启动。")
        }
        JSONObject().put("status", "started").put("id", token)
    }

    fun snapshot(): JSONObject = synchronized(lock) {
        JSONObject(tasks.getString("current", "{\"status\":\"idle\",\"stage\":\"idle\",\"message\":\"当前没有任务\",\"percent\":0}")!!)
    }

    fun cancel(): JSONObject = synchronized(lock) {
        val value = snapshot()
        if (value.optString("status") == "running") {
            value.put("status", "cancelled").put("stage", "cancelled").put("message", "已中止；当前请求返回后退出，已保存文章保留。")
            save(value)
            value.optString("work_id").takeIf { it.isNotEmpty() }?.let { WorkManager.getInstance(context).cancelWorkById(UUID.fromString(it)) }
        }
        value
    }

    fun run(token: String, date: String, expected: Long, generation: String, isStopped: () -> Boolean) {
        val check = {
            val current = snapshot()
            check(DataDirectory.hasAccess(context)) { "文庫存储权限已关闭，请打开 APP 重新授权。" }
            if (isStopped() || current.optString("id") != token || current.optString("status") != "running") throw CancellationException("日刊任务已中止。")
            if (expected > 0 && (preferences.getString("daily-schedule-generation", "") != generation ||
                    JSONObject(preferences.getString("setting:daily-schedule", "{}")!!).optString("mode") != "automatic")) throw CancellationException("自动更新设置已变更。")
            if (expected > 0 && !CstSchedule.accept(Instant.ofEpochMilli(expected), Instant.now())) throw MissedScheduleWindow()
        }
        try {
            if (expected > 0 && !CstSchedule.accept(Instant.ofEpochMilli(expected), Instant.now())) {
                update(token, JSONObject().put("status", "interrupted").put("stage", "interrupted").put("message", "系统错过本次更新窗口；不补跑旧日刊。"))
                return
            }
            check()
            PublicHttpClient.requireNetwork(context)
            val sourceJson = preferences.getString("setting:news-sources", null)?.let(::JSONArray)
            val browserVoiceName = JSONObject(preferences.getString("setting:voice-mode", "{\"browser_voice_name\":\"ja-JP-KeitaNeural\"}")!!)
                .optString("browser_voice_name", "ja-JP-KeitaNeural")
            val homepages = listOf("https://news.web.nhk/newsweb/", "https://www.asahi.com/", "https://www.yomiuri.co.jp/", "https://www.nikkei.com/", "https://www.sankei.com/", "https://news.yahoo.co.jp/")
            val sources = if (sourceJson != null) (0 until sourceJson.length()).map { index -> sourceJson.getJSONObject(index).let {
                DailySource(it.getInt("id"), it.getString("name"), it.getString("homepage"), it.getInt("minimum_count"),
                    it.optString("voice_mode", "inherit"), browserVoiceName)
            } } else NewsProviders.defaults.mapIndexed { index, provider -> DailySource(index + 1, provider.name, homepages[index], 1, "browser", browserVoiceName) }
            val target = JSONObject(preferences.getString("setting:daily-content", "{\"target_count\":10}")!!).getInt("target_count")
            val http = PublicHttpClient(context, check)
            val processor = ArticlePostprocessor(context, http) { stage, message ->
                val progress = snapshot().put("stage", stage).put("message", message)
                update(token, progress)
            }
            var indexed = -1
            var indexError: String? = null
            val result = DailyCoordinator(dataRoot.toPath()).run(DailyRequest(date, target, sources), http, processor::process, check) { progress ->
                val completed = progress.optInt("completed")
                if (completed != indexed) {
                    try { index.rebuild(); indexed = completed; indexError = null; preferences.edit().remove("article-index-error").commit() }
                    catch (_: Exception) {
                        indexError = "文章文件已保留，但索引重建失败；请检查可用空间。"
                        preferences.edit().putString("article-index-error", indexError).commit()
                    }
                }
                indexError?.let { detail ->
                    progress.getJSONArray("errors").put(detail)
                    if (progress.optString("status") == "completed") progress.put("status", "partial").put("stage", "partial").put("percent", 99)
                    progress.put("message", progress.optString("message") + " " + detail)
                }
                update(token, progress)
            }
            update(token, result)
        } catch (_: MissedScheduleWindow) {
            update(token, JSONObject().put("status", "interrupted").put("stage", "interrupted").put("message", "系统错过本次更新窗口；已保存内容保留，不补跑旧日刊。"))
        } catch (_: CancellationException) {
            update(token, JSONObject().put("status", "cancelled").put("stage", "cancelled").put("message", "日刊任务已中止；已保存内容保留。"))
        } catch (failure: Exception) {
            update(token, JSONObject().put("status", "failed").put("stage", "failed").put("percent", 0)
                .put("message", failure.message ?: "日刊未完成，请检查网络和可用空间。"))
        } finally {
            // Retain allocation gaps even when cancellation occurs before file commit.
            try { index.rebuild(); preferences.edit().remove("article-index-error").commit() }
            catch (_: Exception) { preferences.edit().putString("article-index-error", "文章文件已保留，但索引重建失败；请检查可用空间。").commit() }
        }
    }

    private fun update(token: String, progress: JSONObject) = synchronized(lock) {
        val current = snapshot()
        if (current.optString("id") == token && current.optString("status") == "running") {
            progress.keys().forEach { key -> if (key !in setOf("id", "work_id")) current.put(key, progress.get(key)) }
            save(current)
        }
    }
    private fun save(value: JSONObject) { check(tasks.edit().putString("current", value.toString()).commit()) { "任务状态保存失败，请检查可用空间。" } }
    private class MissedScheduleWindow : CancellationException()

    companion object {
        @Volatile private var instance: DailyRuntime? = null
        fun get(context: Context): DailyRuntime = instance ?: synchronized(this) {
            instance ?: DailyRuntime(context.applicationContext).also { instance = it }
        }
    }
}

class DailyWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val token = inputData.getString("token") ?: return Result.failure()
        val date = inputData.getString("date") ?: return Result.failure()
        DailyRuntime.get(applicationContext).run(token, date, inputData.getLong("expected", 0), inputData.getString("scheduleGeneration") ?: "") { isStopped }
        return if (DailyRuntime.get(applicationContext).snapshot().optString("status") == "failed") Result.failure() else Result.success()
    }
}
