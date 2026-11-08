package jp.fujimi.newsbunko.next.store

import java.nio.file.Path
import java.nio.file.Files
import java.nio.file.LinkOption
import java.net.URI
import java.net.URLEncoder
import java.security.MessageDigest
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption
import java.nio.file.StandardCopyOption
import java.nio.file.AtomicMoveNotSupportedException
import java.time.Instant
import org.json.JSONObject
import org.json.JSONArray
import org.jsoup.Jsoup
import org.jsoup.safety.Safelist

class LocalSyncedLibraryApi(private val dataRoot: Path, voiceSettings: () -> JSONObject = { JSONObject() },
    browserVoices: () -> JSONArray = { JSONArray() }) {
    private val root = dataRoot.toAbsolutePath().normalize()
    private val savedVoiceAudio = SavedVoiceAudio(dataRoot, voiceSettings, browserVoices)
    private val selectedChapters = java.util.concurrent.ConcurrentHashMap<String, JSONObject>()
    private val markup = Safelist.relaxed().addTags("ruby", "rt", "rp", "rb").addAttributes(":all", "class", "id")
        .addAttributes("img", "data-book-asset").addAttributes("a", "data-book-href")
        .addProtocols("a", "href", "#").preserveRelativeLinks(true)

    fun request(method: String, path: String, body: String? = null): ApiResponse? {
        val uri = URI("https://local$path")
        val route = uri.path
        stateRequest(method, route, body)?.let { return it }
        if (method == "POST" && Regex("/api/books/\\d+/chapters/\\d+/reread").matches(route)) {
            val selection = runCatching { JSONObject(body ?: "{}") }.getOrNull() ?: return error(400, "声线选择无效。")
            if (savedVoiceAudio.choice(selection) == null) return error(409, "PC 声线须先在 PC 生成完整朗读后同步。")
            val chapterRoute = route.removeSuffix("/reread")
            val previous = selectedChapters.put(chapterRoute, selection)
            val response = request("GET", chapterRoute)
            val chapter = response?.takeIf { it.status == 200 }?.let { JSONObject(it.body).getJSONObject("chapter") }
            if (chapter?.optJSONObject("audio")?.optString("status") == "ready") return ApiResponse(200, JSONObject().put("status", "ready").put("cached", true).toString())
            if (previous == null) selectedChapters.remove(chapterRoute) else selectedChapters[chapterRoute] = previous
            return error(409, chapter?.optString("audio_unavailable_detail")?.takeIf { it.isNotEmpty() } ?: "所选声线的完整朗读尚未同步，请先在 PC 生成后同步。")
        }
        if (method != "GET" || !(route == "/api/examples" || route == "/api/books" || route.startsWith("/api/books/"))) return null
        return try {
            val value: Any = when {
                route == "/api/examples" -> examples()
                route == "/api/books/tasks" -> JSONObject().put("tasks", JSONArray())
                route == "/api/books" -> {
                    val books = folders("books", "book.json").map { book(it) }
                    val sort = uri.rawQuery.orEmpty().substringAfter("sort=", "recent").substringBefore('&')
                    val sorted = if (sort == "series") books.sortedWith(compareBy({ it.optString("series") }, { it.optString("volume") }, { it.optString("title") }))
                        else books.sortedByDescending { if (sort == "recent") it.optString("last_read_at").ifEmpty { it.optString("imported_at") } else it.optString("imported_at") }
                    JSONObject().put("books", JSONArray(sorted))
                }
                Regex("/api/books/\\d+").matches(route) -> book(bookFolder(route.substringAfterLast('/').toLong()))
                Regex("/api/books/\\d+/chapters/\\d+").matches(route) -> {
                    val segments = route.split('/')
                    val folder = bookFolder(segments[3].toLong())
                    val metadata = book(folder)
                    val chapters = metadata.getJSONArray("chapters")
                    val chapterId = segments[5].toLong()
                    val summary = (0 until chapters.length()).map { chapters.getJSONObject(it) }
                        .firstOrNull { it.getLong("id") == chapterId } ?: throw NoSuchElementException("章节不存在。")
                    val chapter = JSONObject(verified(folder, summary.getString("file"), summary.getString("sha256")).toString(Charsets.UTF_8))
                    val blocks = chapter.optJSONArray("blocks") ?: JSONArray()
                    for (index in 0 until blocks.length()) {
                        val block = blocks.getJSONObject(index)
                        for (field in listOf("html", "furigana_html")) if (block.has(field)) block.put(field, Jsoup.clean(block.getString(field), markup))
                    }
                    if (!chapter.has("voice_mode")) chapter.put("voice_mode", "browser")
                    savedVoiceAudio.chapter(chapter, selectedChapters[route]) { relative -> runCatching { audioAsset(segments[3].toLong(), relative) }.isSuccess }
                    chapter.optJSONObject("audio")?.let { audio ->
                        val relative = audio.optString("path")
                        if (relative.isNotEmpty()) {
                            audioAsset(segments[3].toLong(), relative)
                            audio.put("url", "/api/books/${segments[3]}/audio/${encodePath(relative)}")
                        }
                    }
                    JSONObject().put("book", metadata).put("chapter", chapter)
                }
                else -> return null
            }
            ApiResponse(200, value.toString())
        } catch (failure: NoSuchElementException) { error(404, failure.message ?: "内容不存在。") }
        catch (failure: Exception) { error(409, failure.message ?: "文庫文件校验失败。") }
    }

    private fun stateRequest(method: String, route: String, body: String?): ApiResponse? {
        val progress = Regex("/api/books/(\\d+)/progress").matchEntire(route)?.takeIf { method == "PUT" }
        val bookmark = Regex("/api/books/(\\d+)/chapters/(\\d+)/bookmarks").matchEntire(route)?.takeIf { method == "POST" }
        val matched = progress ?: bookmark ?: return null
        return try {
            ArticleStore(root).withSyncLock {
                val payload = JSONObject(body ?: "{}")
                val id = matched.groupValues[1].toLong()
                val folder = bookFolder(id)
                val metadata = book(folder)
                val chapterId = if (progress != null) integer(payload, "chapter_id") else bookmark!!.groupValues[2].toLong()
                val summaries = metadata.getJSONArray("chapters")
                val summary = (0 until summaries.length()).map { summaries.getJSONObject(it) }
                    .firstOrNull { it.getLong("id") == chapterId } ?: throw NoSuchElementException("章节不存在。")
                val chapter = JSONObject(String(verified(folder, summary.getString("file"), summary.getString("sha256")), Charsets.UTF_8))
                val blocks = chapter.optJSONArray("blocks") ?: JSONArray()
                val state = json(folder, "state.json")
                val result: Any
                if (progress != null) {
                    val saved = state.optJSONObject("progress") ?: JSONObject()
                    saved.put("chapter_id", chapterId).put("block_index", integer(payload, "block_index", 0).coerceIn(0, maxOf(0, blocks.length() - 1).toLong()))
                    for (key in listOf("audio_time", "scroll_left", "scroll_offset")) if (payload.has(key)) {
                        val raw = payload.get(key)
                        require(raw is Number && raw.toDouble().isFinite() && (key != "audio_time" || raw.toDouble() >= 0)) { "阅读位置无效。" }
                        saved.put(key, raw)
                    }
                    for ((key, allowed) in listOf("reading_mode" to setOf("horizontal", "vertical"), "language_mode" to setOf("parallel", "click", "ja", "zh"))) if (payload.has(key)) {
                        val value = payload.getString(key); require(value in allowed) { "阅读模式无效。" }; saved.put(key, value)
                    }
                    state.put("progress", saved).put("last_read_at", Instant.now().toString())
                    writeState(folder, state)
                    result = book(folder)
                } else {
                    val position = integer(payload, "block_index")
                    require(position >= 0 && position < blocks.length()) { "段落不存在。" }
                    val index = position.toInt()
                    val saved = state.optJSONArray("bookmarks") ?: JSONArray()
                    val existing = (0 until saved.length()).any { saved.getJSONObject(it).optLong("chapter_id") == chapterId && saved.getJSONObject(it).optInt("block_index", -1) == index }
                    val replacement = JSONArray()
                    if (!existing) {
                        val block = blocks.getJSONObject(index)
                        val text = block.optString("text_ja").ifBlank { block.optString("text_zh") }
                        val end = text.offsetByCodePoints(0, minOf(500, text.codePointCount(0, text.length)))
                        replacement.put(JSONObject().put("chapter_id", chapterId).put("block_index", index).put("excerpt", text.substring(0, end)))
                    }
                    state.put("bookmarks", replacement); writeState(folder, state)
                    result = JSONObject().put("bookmarked", !existing)
                }
                ApiResponse(200, result.toString())
            }
        } catch (failure: NoSuchElementException) { error(404, failure.message ?: "内容不存在。") }
        catch (failure: IllegalArgumentException) { error(400, failure.message ?: "阅读状态无效。") }
        catch (failure: Exception) { error(409, failure.message ?: "阅读状态未能保存。") }
    }

    private fun integer(payload: JSONObject, key: String, fallback: Long? = null): Long {
        if (!payload.has(key) && fallback != null) return fallback
        val value = payload.get(key)
        require(value is Number && value.toDouble().isFinite() && value.toDouble() == value.toLong().toDouble()) { "阅读位置须为整数。" }
        return value.toLong()
    }

    private fun writeState(folder: Path, state: JSONObject) {
        val destination = safe(folder, "state.json")
        val temporary = Files.createTempFile(folder, ".state-", ".tmp")
        try {
            FileChannel.open(temporary, StandardOpenOption.WRITE).use { channel ->
                val bytes = ByteBuffer.wrap(state.toString().toByteArray(Charsets.UTF_8))
                while (bytes.hasRemaining()) channel.write(bytes)
                channel.force(true)
            }
            try { Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING) }
            catch (_: AtomicMoveNotSupportedException) { Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING) }
        } finally { Files.deleteIfExists(temporary) }
    }

    private fun folders(relative: String, manifest: String): List<Path> {
        val base = safe(root, relative)
        if (!Files.exists(base, LinkOption.NOFOLLOW_LINKS)) return emptyList()
        return Files.list(base).use { stream -> stream.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) && Files.exists(it.resolve(manifest)) }
            .map { safe(base, it.fileName.toString()) }.iterator().asSequence().toList() }
    }

    private fun bookFolder(id: Long): Path = folders("books", "book.json").firstOrNull {
        json(it, "book.json").getJSONObject("book").getLong("id") == id
    } ?: throw NoSuchElementException("书籍不存在。")

    private fun book(folder: Path): JSONObject {
        val manifest = json(folder, "book.json")
        require(manifest.getInt("version") == 2) { "不支持的书籍文件版本。" }
        verifyPath(folder, manifest.getString("source_file"), manifest.getString("source_sha256"))
        val book = manifest.getJSONObject("book")
        val state = json(folder, "state.json")
        for (field in listOf("progress", "bookmarks", "last_read_at")) if (state.has(field)) book.put(field, state.get(field))
        book.put("cover_url", if (book.optString("cover_path").isEmpty()) "" else "/api/books/${book.getLong("id")}/assets/${book.getString("cover_path")}")
        return book
    }

    fun asset(id: Long, path: String): Path {
        val folder = bookFolder(id)
        val resources = json(folder, "book.json").getJSONObject("resources")
        require(resources.has(path)) { "书籍资源未登记。" }
        val base = safe(folder, "resources")
        return verifyPath(base, path, resources.getJSONObject(path).getString("sha256"))
    }

    fun audioAsset(id: Long, path: String): Path {
        require(path.endsWith(".wav", true) || path.endsWith(".mp3", true)) { "书籍音频格式不支持。" }
        val folder = bookFolder(id)
        val entry = json(folder, "book.json").getJSONObject("audio").optJSONObject(path)
            ?: throw IllegalArgumentException("书籍音频未登记。")
        val base = safe(folder, "audio")
        return verifyPath(base, path, entry.getString("sha256"))
    }

    private fun examples(): JSONArray = JSONArray(folders("articles/examples", "example.json").map { folder ->
        val manifest = json(folder, "example.json")
        manifest.put("text", verified(folder, "original.txt", manifest.getString("text_sha256")).toString(Charsets.UTF_8))
        val translations = if (manifest.has("translation_sha256")) verified(folder, "translation.txt", manifest.getString("translation_sha256"))
            .toString(Charsets.UTF_8).split("\n\n") else emptyList()
        manifest.put("translated_paragraphs", JSONArray(translations))
    })

    private fun json(base: Path, path: String) = JSONObject(String(Files.readAllBytes(safe(base, path)), Charsets.UTF_8))
    private fun encodePath(path: String) = path.split('/').joinToString("/") { URLEncoder.encode(it, "UTF-8").replace("+", "%20") }
    private fun verified(base: Path, path: String, sha: String): ByteArray {
        return Files.readAllBytes(verifyPath(base, path, sha))
    }
    private fun verifyPath(base: Path, path: String, sha: String): Path {
        val file = safe(base, path)
        val digest = MessageDigest.getInstance("SHA-256")
        Files.newInputStream(file).use { input ->
            val buffer = ByteArray(65536)
            while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
        }
        val actual = digest.digest().joinToString("") { "%02x".format(it) }
        require(actual == sha) { "文件缺失或校验失败：$path" }
        return file
    }
    private fun safe(base: Path, relative: String): Path {
        require(relative.isNotEmpty() && !relative.startsWith('/') && '\\' !in relative && ':' !in relative && '\u0000' !in relative) { "无效文庫路径。" }
        val parts = relative.split('/')
        require(parts.all { it.isNotEmpty() && it != "." && it != ".." }) { "文庫路径越界。" }
        var current = base.toAbsolutePath().normalize()
        require(current.startsWith(root) && !Files.isSymbolicLink(current)) { "文庫路径越界。" }
        var ancestor = root
        for (part in root.relativize(current)) { ancestor = ancestor.resolve(part); require(!Files.isSymbolicLink(ancestor)) { "文庫路径包含符号链接。" } }
        for (part in parts) { current = current.resolve(part); require(!Files.isSymbolicLink(current)) { "文庫路径包含符号链接。" } }
        return current
    }
    private fun error(status: Int, detail: String) = ApiResponse(status, JSONObject().put("detail", detail).toString())
}
