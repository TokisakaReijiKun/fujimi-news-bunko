package jp.fujimi.newsbunko.next.settings

import jp.fujimi.newsbunko.next.store.ApiResponse
import jp.fujimi.newsbunko.next.store.LocalVoiceStore
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.nio.file.Path

interface SettingsBackend {
    fun read(key: String): String?
    fun write(key: String, value: String)
}

class LocalSettingsApi(
    private val backend: SettingsBackend,
    private val dailySchedule: DailyScheduleService? = null,
    private val referenceVoices: LocalVoiceStore? = null,
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

    fun browserVoices(): JSONArray = browserVoices(false)
    fun browserVoices(includeHidden: Boolean): JSONArray {
        val result = JSONArray(voices().toString())
        val known = (0 until result.length()).map { result.getJSONObject(it).getString("id") }.toMutableSet()
        val remote = runCatching { JSONArray(backend.read("pc-browser-voices") ?: "[]") }.getOrDefault(JSONArray())
        for (i in 0 until remote.length()) {
            val voice = remote.optJSONObject(i) ?: continue
            val id = voice.optString("id"); val name = voice.optString("name")
            if (id.isBlank() || name.isBlank() || id.length > 200 || name.length > 100 || !known.add(id)) continue
            result.put(JSONObject().put("id", id).put("name", name).put("provider", voice.optString("provider"))
                .put("lang", voice.optString("lang", "ja-JP")).put("available", true).put("saved_audio_only", true).put("local", false))
        }
        val edits = customizations().optJSONObject("browser") ?: JSONObject()
        return JSONArray((0 until result.length()).map { result.getJSONObject(it) }.filter { voice ->
            if (voice.optBoolean("read_only")) return@filter true
            val edit = edits.optJSONObject(voice.getString("id"))
            edit?.optString("name")?.takeIf { it.isNotBlank() }?.let { voice.put("name", it) }
            voice.put("hidden", edit?.optBoolean("hidden") ?: false)
            includeHidden || !voice.getBoolean("hidden")
        })
    }

    private fun customizations() = JSONObject(backend.read("voice-customizations") ?: "{}")
    private fun label(payload: JSONObject): String = payload.getString("name").trim().also {
        require(it.isNotBlank() && it.length <= 80 && it.none(Char::isISOControl)) { "声线名称须为 1–80 个字符。" }
    }
    private fun voiceRows(): JSONArray {
        val labels = customizations().optJSONObject("reference") ?: JSONObject()
        val mode = value("voice-mode")
        val rows = referenceVoices?.list(mode.takeIf { it.optString("mode") == "voice" }?.optLong("voice_id")) ?: JSONArray()
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            labels.optString(row.getLong("id").toString()).takeIf { it.isNotBlank() }?.let { row.put("name", it) }
        }
        return rows
    }

    private fun manageBrowser(method: String, payload: JSONObject, file: Path?): ApiResponse {
        val id = payload.getString("id")
        val catalog = browserVoices(true)
        require((0 until catalog.length()).any { catalog.getJSONObject(it).getString("id") == id }) { "声线不存在。" }
        require((0 until catalog.length()).none { catalog.getJSONObject(it).let { row -> row.getString("id") == id && row.optBoolean("read_only") } }) { "系统音声不能修改或删除。" }
        val edits = customizations()
        val browser = edits.optJSONObject("browser") ?: JSONObject().also { edits.put("browser", it) }
        val entry = browser.optJSONObject(id) ?: JSONObject()
        if (file != null && method in setOf("POST", "PUT")) {
            val title = label(payload)
            val row = (referenceVoices ?: return error(501, "此设备不能管理声线文件。")).saveFile(title, file)
            val labels = edits.optJSONObject("reference") ?: JSONObject().also { edits.put("reference", it) }
            labels.put(row.getLong("id").toString(), title)
            browser.put(id, entry.put("hidden", true))
            backend.write("voice-customizations", edits.toString())
            val mode = value("voice-mode")
            if (mode.optString("mode") == "browser" && mode.optString("browser_voice_name") == id) {
                save("voice-mode", mode.put("mode", "voice").put("voice_id", row.getLong("id")))
            }
            return ok(JSONObject().put("ok", true).put("voice_id", row.getLong("id")))
        }
        when (method) {
            "POST", "PUT" -> entry.put("name", label(payload)).put("hidden", false)
            "DELETE" -> entry.put("hidden", true)
            else -> return error(405, "不支持此请求方式。")
        }
        browser.put(id, entry); backend.write("voice-customizations", edits.toString())
        val mode = value("voice-mode")
        if (mode.optString("browser_voice_name") == id) {
            if (method == "DELETE" && mode.optString("mode") == "browser") mode.put("mode", "none")
            else if (entry.has("name")) mode.put("browser_voice_label", entry.getString("name"))
            save("voice-mode", mode)
        }
        return ok(JSONObject().put("ok", true))
    }

    private fun manageReference(method: String, id: Long?, payload: JSONObject, file: Path?): ApiResponse {
        val store = referenceVoices ?: return error(501, "此设备不能管理声线文件。")
        val edits = customizations()
        val labels = edits.optJSONObject("reference") ?: JSONObject().also { edits.put("reference", it) }
        if (method == "DELETE" && id != null) {
            store.delete(id); labels.remove(id.toString())
            val mode = value("voice-mode")
            if (mode.optString("mode") == "voice" && mode.optLong("voice_id") == id) save("voice-mode", mode.put("mode", "none").put("voice_id", JSONObject.NULL))
        } else if (method in setOf("POST", "PUT")) {
            val name = label(payload)
            val row = if (file != null) store.saveFile(name, file, id)
                else id?.let { store.find(it) } ?: return error(400, "请选择 WAV 音频文件。")
            labels.put(row.getLong("id").toString(), name)
        } else return error(405, "不支持此请求方式。")
        backend.write("voice-customizations", edits.toString())
        return ok(JSONObject().put("ok", true))
    }

    fun savePcBrowserVoices(voices: JSONArray) {
        require(voices.length() <= 100) { "PC 声线目录过大。" }
        val catalog = JSONArray()
        for (i in 0 until voices.length()) {
            val voice = voices.getJSONObject(i)
            val id = voice.getString("id"); val name = voice.getString("name")
            require(id.isNotBlank() && id.length <= 200 && name.isNotBlank() && name.length <= 100)
            catalog.put(JSONObject().put("id", id).put("name", name).put("provider", voice.optString("provider"))
                .put("lang", voice.optString("lang", "ja-JP")))
        }
        backend.write("pc-browser-voices", catalog.toString())
    }

    @Synchronized
    fun request(method: String, path: String, body: String?, voiceFile: Path? = null): ApiResponse? {
        if (!path.startsWith("/api/settings/") && path != "/api/browser-voices") return null
        return try {
            val payload = if (body.isNullOrBlank()) JSONObject() else JSONObject(body)
            when {
                path == "/api/settings/daily-schedule" && dailySchedule != null -> {
                    if (method == "GET") ok(dailySchedule.status())
                    else if (method == "PUT") {
                        val mode = payload.getString("mode")
                        val time = payload.getString("time")
                        require(mode in setOf("manual", "automatic")) { "更新模式不正确。" }
                        require(Regex("(?:[01]\\d|2[0-3]):[0-5]\\d").matches(time)) { "更新时间不正确。" }
                        ok(dailySchedule.configure(mode, time))
                    } else error(405, "不支持此请求方式。")
                }
                path == "/api/browser-voices" && method == "GET" -> ok(browserVoices())
                path == "/api/settings/voice-catalog" && method == "GET" -> ok(browserVoices(true))
                path == "/api/settings/browser-voices" -> manageBrowser(method, payload, voiceFile)
                path == "/api/settings/voices" -> if (method == "GET") ok(voiceRows()) else manageReference(method, null, payload, voiceFile)
                Regex("/api/settings/voices/\\d+").matches(path) -> manageReference(method, path.substringAfterLast('/').toLong(), payload, voiceFile)
                path == "/api/settings/browser-voice" && method == "PUT" -> {
                    val name = payload.getString("name")
                    val catalog = browserVoices()
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
                    val mode = value("voice-mode")
                    if (payload.optBoolean("disabled")) mode.put("mode", "none")
                    else if (payload.optBoolean("browser")) mode.put("mode", "browser")
                    else {
                        val id = payload.getLong("voice_id")
                        require(referenceVoices?.find(id) != null) { "所选参考声线尚未同步或文件无效。" }
                        mode.put("mode", "voice").put("voice_id", id)
                    }
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
                            "daily-content" -> {
                                val target = integer(payload, "target_count", 1, 500)
                                require(target >= sourceMinimumTotal(sources())) { "記事数は各ソースの最低合計以上にしてください。" }
                                result.put("target_count", target)
                            }
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
        } catch (_: NoSuchElementException) {
            error(404, "声线不存在。")
        } catch (_: java.io.IOException) {
            error(503, "声线文件无法读写，请检查存储空间。")
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
        sources.put(source)
        validateSourceTotal(sources)
        backend.write("news-source-sequence", (lastId + 1).toString())
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
        validateSourceTotal(sources)
        backend.write("news-sources", sources.toString())
        return ok(result)
    }

    private fun sourceMinimumTotal(sources: JSONArray): Int = (0 until sources.length()).sumOf { sources.getJSONObject(it).optInt("minimum_count") }
    private fun validateSourceTotal(sources: JSONArray) {
        require(sourceMinimumTotal(sources) <= value("daily-content").getInt("target_count")) { "各ソースの最低合計は記事数を超えられません。" }
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
