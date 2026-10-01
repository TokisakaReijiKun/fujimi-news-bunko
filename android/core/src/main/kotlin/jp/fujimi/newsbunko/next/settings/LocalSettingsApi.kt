package jp.fujimi.newsbunko.next.settings

import jp.fujimi.newsbunko.next.store.ApiResponse
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI

interface SettingsBackend {
    fun read(key: String): String?
    fun write(key: String, value: String)
}

class LocalSettingsApi(
    private val backend: SettingsBackend,
    private val voices: () -> JSONArray,
) {
    private val defaults = mapOf(
        "library" to "{\"sort\":\"recent\",\"lookup_chinese_translations\":true}",
        "daily-schedule" to "{\"mode\":\"manual\",\"time\":\"00:00\"}",
        "daily-content" to "{\"target_count\":10}",
        "voice-mode" to "{\"mode\":\"browser\",\"browser_voice_name\":\"ja-JP-KeitaNeural\",\"browser_voice_label\":\"システム音声\"}",
    )

    @Synchronized
    fun value(key: String): JSONObject = JSONObject(backend.read(key) ?: defaults.getValue(key))

    @Synchronized
    fun request(method: String, path: String, body: String?): ApiResponse? {
        if (!path.startsWith("/api/settings/") && path != "/api/browser-voices") return null
        return try {
            val payload = if (body.isNullOrBlank()) JSONObject() else JSONObject(body)
            when {
                path == "/api/browser-voices" && method == "GET" -> ok(voices())
                path == "/api/settings/voices" && method == "GET" -> ok(JSONArray())
                path == "/api/settings/browser-voice" && method == "PUT" -> {
                    val name = payload.getString("name")
                    val catalog = voices()
                    require((0 until catalog.length()).any {
                        val voice = catalog.getJSONObject(it)
                        voice.optString("id") == name && voice.optBoolean("available", true)
                    }) { "此设备没有可用的所选 Edge 声线。" }
                    val label = payload.optString("label", "システム音声").trim()
                    require(label.isNotEmpty() && label.length <= 100) { "声线名称须为 1–100 个字符。" }
                    val mode = value("voice-mode").put("mode", "browser")
                        .put("browser_voice_name", name).put("browser_voice_label", label)
                    save("voice-mode", mode)
                    ok(mode)
                }
                path == "/api/settings/active-voice" && method == "PUT" -> {
                    require(payload.optBoolean("browser")) { "手机独立朗读仅支持圭太或七海 Edge 在线声线。" }
                    val mode = value("voice-mode").put("mode", "browser")
                    save("voice-mode", mode)
                    ok(mode)
                }
                path == "/api/settings/news-sources" -> sourcesRequest(method, payload)
                Regex("/api/settings/news-sources/\\d+").matches(path) -> sourceRequest(method, path.substringAfterLast('/').toInt(), payload)
                path.substringAfterLast('/') in defaults -> {
                    val key = path.substringAfterLast('/')
                    val result = value(key)
                    if (method == "PUT") {
                        when (key) {
                            "library" -> {
                                val sort = payload.optString("sort", result.getString("sort"))
                                require(sort in setOf("recent", "series", "imported")) { "书架排序方式不正确。" }
                                if (payload.has("lookup_chinese_translations")) require(payload.get("lookup_chinese_translations") is Boolean) { "查词选项须为布尔值。" }
                                result.put("sort", sort).put("lookup_chinese_translations", payload.optBoolean("lookup_chinese_translations", result.getBoolean("lookup_chinese_translations")))
                            }
                            "daily-content" -> result.put("target_count", integer(payload, "target_count", 1, 500))
                            "daily-schedule" -> {
                                require(payload.optString("mode") in setOf("manual", "automatic")) { "更新模式不正确。" }
                                require(Regex("(?:[01]\\d|2[0-3]):[0-5]\\d").matches(payload.optString("time"))) { "更新时间不正确。" }
                                if (payload.getString("mode") == "automatic") return error(501, "Android 日刊采集与后台调度尚未接入，暂时仅支持手动模式。")
                                result.put("mode", "manual").put("time", payload.getString("time"))
                            }
                            else -> return error(405, "请通过声线选择接口修改此设置。")
                        }
                        save(key, result)
                    } else if (method != "GET") return error(405, "不支持此请求方式。")
                    if (key == "daily-content") {
                        val sources = sources()
                        result.put("source_count", sources.length()).put("required_count", (0 until sources.length()).sumOf { sources.getJSONObject(it).optInt("minimum_count") })
                    }
                    if (key == "daily-schedule") result.put("timezone", "Asia/Shanghai").put("scheduler_available", false).put("next_run", JSONObject.NULL)
                    ok(result)
                }
                else -> error(501, "此设置操作尚未接入 Android；未更改数据。")
            }
        } catch (error: IllegalArgumentException) {
            error(400, error.message ?: "设置格式无效。")
        } catch (error: org.json.JSONException) {
            error(400, "设置字段缺失或类型无效。")
        }
    }

    private fun sources(): JSONArray = JSONArray(backend.read("news-sources") ?: JSONArray().apply {
        val publishers = listOf(
            "NHKニュース" to "https://news.web.nhk/newsweb/",
            "朝日新聞" to "https://www.asahi.com/",
            "読売新聞" to "https://www.yomiuri.co.jp/",
            "日本経済新聞" to "https://www.nikkei.com/",
            "産経新聞" to "https://www.sankei.com/",
            "Yahoo!ニュース" to "https://news.yahoo.co.jp/",
        )
        publishers.forEachIndexed { index, (name, homepage) -> put(JSONObject().put("id", index + 1).put("name", name).put("homepage", homepage).put("minimum_count", 1).put("voice_mode", "browser").put("voice_id", JSONObject.NULL)) }
    }.toString())

    private fun sourcesRequest(method: String, payload: JSONObject): ApiResponse {
        val sources = sources()
        if (method == "GET") return ok(sources)
        if (method != "POST") return error(405, "不支持此请求方式。")
        val source = validateSource(payload)
        val lastId = (backend.read("news-source-sequence")?.toIntOrNull() ?: 6).coerceAtLeast((0 until sources.length()).maxOfOrNull { sources.getJSONObject(it).getInt("id") } ?: 0)
        source.put("id", lastId + 1)
        backend.write("news-source-sequence", (lastId + 1).toString())
        sources.put(source)
        backend.write("news-sources", sources.toString())
        return ok(source)
    }

    private fun sourceRequest(method: String, id: Int, payload: JSONObject): ApiResponse {
        val sources = sources()
        val index = (0 until sources.length()).firstOrNull { sources.getJSONObject(it).getInt("id") == id } ?: return error(404, "来源不存在。")
        val result = when (method) {
            "DELETE" -> { sources.remove(index); JSONObject().put("ok", true) }
            "PUT" -> {
                val current = sources.getJSONObject(index)
                payload.keys().forEach { current.put(it, payload.get(it)) }
                validateSource(current).put("id", id).also { sources.put(index, it) }
            }
            else -> return error(405, "不支持此请求方式。")
        }
        backend.write("news-sources", sources.toString())
        return ok(result)
    }

    private fun validateSource(payload: JSONObject): JSONObject {
        val name = payload.optString("name").trim()
        require(name.isNotEmpty() && name.length <= 100) { "请输入 1–100 字的来源名称。" }
        val homepage = URI(payload.getString("homepage"))
        require(homepage.scheme == "https" && homepage.host != null && homepage.userInfo == null && homepage.fragment == null) { "请输入有效的 HTTPS 来源网址。" }
        val mode = payload.optString("voice_mode", "inherit")
        require(mode in setOf("inherit", "browser", "none")) { "手机来源仅支持 Edge 在线朗读、沿用全局或无朗读。" }
        return JSONObject().put("name", name).put("homepage", homepage.toASCIIString())
            .put("minimum_count", integer(payload, "minimum_count", 0, 100)).put("voice_mode", mode).put("voice_id", JSONObject.NULL)
    }

    private fun integer(payload: JSONObject, key: String, min: Int, max: Int): Int {
        val raw = payload.get(key)
        require(raw is Number && raw.toDouble() == raw.toInt().toDouble() && raw.toInt() in min..max) { "$key 须为 $min–$max 的整数。" }
        return raw.toInt()
    }

    private fun save(key: String, value: JSONObject) = backend.write(key, value.toString())
    private fun ok(value: Any) = ApiResponse(200, value.toString())
    private fun error(code: Int, detail: String) = ApiResponse(code, JSONObject().put("detail", detail).toString())
}
