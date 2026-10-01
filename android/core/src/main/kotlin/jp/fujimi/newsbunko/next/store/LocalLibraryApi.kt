package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.net.URLDecoder
import java.nio.file.Path
import java.time.LocalDate
import java.time.ZoneId

data class ApiResponse(val status: Int, val body: String)

/** The subset of the existing Web API backed by verified local article files. */
class LocalLibraryApi(private val dataRoot: Path) {
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
                    ok(JSONObject().put("date", date)
                        .put("articles", JSONArray(items.map { it.metadata }))
                        .put("source_counts", JSONObject())
                        .put("missing_sources", JSONArray())
                        .put("generation_running", false))
                }
                path == "/api/bookmarks" -> ok(JSONArray(catalog.days().flatMap(catalog::onDay)
                    .filter { it.metadata.optBoolean("bookmarked") }
                    .map { JSONObject(it.metadata.toString()).put("bookmark_context", true) }))
                Regex("/api/articles/\\d+").matches(path) -> {
                    val id = path.substringAfterLast('/').toLong()
                    ok(catalog.find(id).metadata)
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

    private fun ok(value: JSONObject) = ApiResponse(200, value.toString())
    private fun ok(value: JSONArray) = ApiResponse(200, value.toString())
    private fun error(status: Int, message: String) = ApiResponse(status, JSONObject().put("detail", message).toString())
}
