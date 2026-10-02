package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.file.Path
import java.time.LocalDate
import java.time.ZoneId

data class ApiResponse(val status: Int, val body: String)

/** The subset of the existing Web API backed by verified local article files. */
class LocalLibraryApi(private val dataRoot: Path, private val taskState: () -> JSONObject = { JSONObject() }) {
    private val catalog = ArticleCatalog(dataRoot)

    fun request(method: String, pathWithQuery: String): ApiResponse {
        if (method != "GET") return error(501, "此操作尚未接入 Android 本地存储。")
        try {
            val uri = URI("https://local$pathWithQuery")
            val path = uri.path
            return when {
                path == "/api/health" -> ok(JSONObject()
                    .put("status", "ok").put("runtime", "android")
                    .put("dictionary", false).put("translation_configured", false)
                    .put("tts", "browser").put("tts_details", JSONObject().put("enabled", false)))
                path == "/api/days" -> ok(JSONArray(catalog.days()))
                path == "/api/daily" -> {
                    val query = uri.rawQuery?.split('&')?.firstOrNull { it.startsWith("date=") }?.substringAfter('=')
                    val date = query?.let { URLDecoder.decode(it, "UTF-8") }
                        ?: LocalDate.now(ZoneId.of("Asia/Shanghai")).toString()
                    val items = catalog.onDay(date)
                    val task = taskState()
                    val counts = items.groupingBy { it.metadata.optString("source_name") }.eachCount()
                    ok(JSONObject().put("date", date)
                        .put("articles", JSONArray(items.map { wire(it.metadata) }))
                        .put("source_counts", JSONObject(counts))
                        .put("missing_sources", if (task.optString("date") == date) task.optJSONArray("missing_sources") ?: JSONArray() else JSONArray())
                        .put("generation_running", task.optString("status") == "running" && task.optString("date") == date))
                }
                path == "/api/bookmarks" -> ok(JSONArray(catalog.days().flatMap(catalog::onDay)
                    .filter { it.metadata.optBoolean("bookmarked") }
                    .map { wire(it.metadata).put("bookmark_context", true) }))
                Regex("/api/articles/\\d+").matches(path) -> {
                    val id = path.substringAfterLast('/').toLong()
                    ok(wire(catalog.find(id).metadata))
                }
                else -> error(404, "接口不存在。")
            }
        } catch (error: NoSuchElementException) {
            return error(404, error.message ?: "内容不存在。")
        } catch (error: ArticleFormatException) {
            return error(409, error.message ?: "文章文件格式无效。")
        } catch (error: IllegalArgumentException) {
            return error(400, error.message ?: "请求格式无效。")
        }
    }

    private fun wire(metadata: JSONObject): JSONObject {
        val article = JSONObject(metadata.toString())
        val prefix = "/api/articles/${article.getLong("id")}/media/"
        val images = article.optJSONArray("image_paths") ?: JSONArray()
        article.put("image_paths", JSONArray((0 until images.length()).map { prefix + encodeMediaPath(images.getString(it).removePrefix("media/")) }))
        val videos = article.optJSONArray("video_urls") ?: JSONArray()
        article.put("video_urls", JSONArray((0 until videos.length()).map { index ->
            val value = videos.getString(index)
            if (value.startsWith("media/")) prefix + encodeMediaPath(value.removePrefix("media/")) else value
        }))
        val audioPath = article.optString("audio_path")
        if (audioPath.startsWith("audio/")) {
            article.put("audio_path", "/api/articles/${article.getLong("id")}/assets/${encodeMediaPath(audioPath)}")
        }
        if (article.optString("audio_path").isEmpty()) {
            val disabled = article.optString("source_voice_mode") == "none" || article.optString("voice_mode") == "none" ||
                article.optString("audio_voice_mode") == "none" || article.optString("audio_status") == "disabled"
            article.put("audio_status", if (disabled) "disabled" else "browser")
                .put("voice_mode", if (disabled) "none" else "browser")
                .put("audio_voice_mode", if (disabled) "none" else "browser")
        }
        return article
    }

    private fun encodeMediaPath(path: String) = path.split('/').joinToString("/") {
        URLEncoder.encode(it, "UTF-8").replace("+", "%20")
    }

    private fun ok(value: JSONObject) = ApiResponse(200, value.toString())
    private fun ok(value: JSONArray) = ApiResponse(200, value.toString())
    private fun error(status: Int, message: String) = ApiResponse(status, JSONObject().put("detail", message).toString())
}
