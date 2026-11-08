package jp.fujimi.newsbunko.next.store

import org.json.JSONObject
import org.json.JSONArray
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.UUID
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream
import java.util.stream.Collectors
import org.jsoup.Jsoup
import org.jsoup.safety.Safelist

class LibrarySyncStore(private val data: Path) {
    private data class Entity(val kind: String, val key: String, val title: String, val folder: Path, val chapterFeatures: JSONObject? = null)
    private var entityIndex: Map<String, Entity>? = null

    companion object {
        private val controlFiles = setOf("article.json", "book.json", "example.json", "state.json")

        /** Sync only fills missing paths; local IDs and reading progress are never revisions. */
        fun needsTransfer(sourceItem: JSONObject, targetItem: JSONObject?): Boolean {
            if (targetItem == null) return true
            if (sourceItem.optString("kind") == "article" && sourceItem.optBoolean("bookmarked") && !targetItem.optBoolean("bookmarked")) return true
            val source = sourceItem.getJSONObject("files")
            val target = targetItem.optJSONObject("files") ?: return true
            val sourceChapters = sourceItem.optJSONObject("chapter_features")
            val targetChapters = targetItem.optJSONObject("chapter_features")
            return source.keys().asSequence().any { name ->
                if (name in controlFiles) false
                else if (!target.has(name)) true
                else if (sourceItem.optString("kind") == "book" && name.startsWith("chapters/") && name.endsWith(".json"))
                    SyncFiles.missingChapterFeatures(sourceChapters, targetChapters, name) ?: (target.getLong(name) != source.getLong(name))
                else target.getLong(name) != source.getLong(name)
            }
        }
    }

    fun manifest(): JSONObject = ArticleStore(data).withSyncLock {
        recover()
        val errors = JSONArray()
        val entities = entities(errors)
        entityIndex = entities.associateBy { it.key }
        JSONObject().put("version", 1).put("file_comparison", "path-size-v1").put("items", JSONArray(entities.map { item ->
            val files = JSONObject()
            paths(item).sorted().forEach { name -> files.put(name, Files.size(SyncFiles.path(item.folder, name))) }
            JSONObject().put("kind", item.kind).put("key", item.key).put("title", item.title).put("files", files).also {
                if (item.kind == "article") it.put("bookmarked", SyncFiles.json(item.folder.resolve("article.json")).getJSONObject("article").optBoolean("bookmarked"))
                item.chapterFeatures?.let { features -> it.put("chapter_features", features) }
            }
        })).put("errors", errors)
    }

    private fun paths(entity: Entity): Set<String> = if (entity.kind == "voice") setOf(entity.title + ".wav")
        else SyncFiles.allowed(entity.kind, entity.folder, allowMissingBookAssets = true)

    /** Describe only the requested speech target; do not scan/export the whole library. */
    fun speechItem(kind: String, id: Long = 0, name: String = ""): JSONObject = ArticleStore(data).withSyncLock {
        recover()
        val item = when (kind) {
            "article" -> entity(kind, SyncFiles.path(data, ArticleCatalog(data).find(id).directory))
            "book" -> entity(kind, directories(data.resolve("books")).firstOrNull {
                runCatching { SyncFiles.json(it.resolve("book.json")).getJSONObject("book").getLong("id") == id }.getOrDefault(false)
            } ?: throw NoSuchElementException("书籍不存在。"))
            "voice" -> {
                require(LocalVoiceStore(data).files().any { LocalVoiceStore.name(it) == name }) { "参考声线不存在。" }
                Entity(kind, LocalVoiceStore.key(name), name, data.resolve("voices"))
            }
            else -> throw IllegalArgumentException("朗读目标无效。")
        }
        entityIndex = entityIndex.orEmpty() + (item.key to item)
        val files = JSONObject()
        paths(item).sorted().forEach { relative -> files.put(relative, Files.size(SyncFiles.path(item.folder, relative))) }
        JSONObject().put("key", item.key).put("kind", item.kind).put("title", item.title).put("files", files).also { value ->
            item.chapterFeatures?.let { value.put("chapter_features", it) }
        }
    }

    private fun indexedEntity(key: String): Entity? {
        if (entityIndex == null) entityIndex = entities(JSONArray()).associateBy { it.key }
        return entityIndex?.get(key)
    }

    fun exportBundle(key: String, destination: Path, knownFiles: JSONObject = JSONObject()) = ArticleStore(data).withSyncLock {
        recover()
        val entity = indexedEntity(key) ?: error("同步项目不存在。")
        val paths = paths(entity)
        if (entity.kind == "voice") LocalVoiceStore.validate(SyncFiles.path(entity.folder, paths.single())) else SyncFiles.validate(entity.kind, entity.folder, verifyContent = false)
        val records = JSONArray(paths.sorted().map { name ->
            val file = SyncFiles.path(entity.folder, name)
            JSONObject().put("path", name).put("size", Files.size(file))
        })
        val included = paths.sorted().filter { name -> name in controlFiles || !knownFiles.has(name) || knownFiles.getLong(name) != Files.size(SyncFiles.path(entity.folder, name)) }
        val description = JSONObject().put("version", 2).put("kind", entity.kind).put("key", entity.key)
            .put("title", entity.title).put("files", records).put("included", JSONArray(included))
        ZipOutputStream(Files.newOutputStream(destination)).use { zip ->
            zip.setLevel(0)
            zip.putNextEntry(ZipEntry("bundle.json")); zip.write(description.toString().toByteArray(Charsets.UTF_8)); zip.closeEntry()
            included.forEach { name ->
                zip.putNextEntry(ZipEntry("files/$name"))
                Files.newInputStream(SyncFiles.path(entity.folder, name)).use { it.copyTo(zip) }
                zip.closeEntry()
            }
        }
    }

    fun importBundle(source: Path): JSONObject {
        val work = data.resolve("diagnostics/sync-staging/${UUID.randomUUID()}")
        val folder = work.resolve("content")
        Files.createDirectories(folder)
        try {
            val description = ZipFile(source.toFile()).use { zip ->
                val entries = zip.entries().asSequence().toList()
                require(entries.size <= 10001 && entries.none { it.isDirectory } && entries.map { it.name.lowercase() }.distinct().size == entries.size) { "同步包条目无效或重复。" }
                val manifest = zip.getEntry("bundle.json") ?: error("同步包缺少清单。")
                require(manifest.size in 1..4 * 1024 * 1024)
                val description = JSONObject(zip.getInputStream(manifest).use { input ->
                    val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
                    while (true) { val n = input.read(buffer); if (n < 0) break; require(output.size() + n <= 4 * 1024 * 1024); output.write(buffer, 0, n) }
                    String(output.toByteArray(), Charsets.UTF_8)
                })
                val version = description.getInt("version")
                require(version in 1..2 && description.getString("kind") in setOf("article", "book", "example", "voice")) { "同步包版本不兼容。" }
                val records = description.getJSONArray("files")
                val recordNames = (0 until records.length()).map { records.getJSONObject(it).getString("path") }.toSet()
                val included = if (version == 1) (0 until records.length()).map { records.getJSONObject(it).getString("path") }
                    else description.getJSONArray("included").let { names -> (0 until names.length()).map { names.getString(it) } }
                val includedNames = included.toSet()
                require(records.length() in 1..10000 && includedNames.size == included.size &&
                    entries.map { it.name }.toSet() == (included.map { "files/$it" } + "bundle.json").toSet()) { "同步包存在未登记文件。" }
                val local = if (included.size < records.length()) ArticleStore(data).withSyncLock { recover(); indexedEntity(description.getString("key")) } else null
                val localPaths = local?.let(::paths).orEmpty()
                require(included.all { it in recordNames }) { "同步包存在未登记文件。" }
                val seen = mutableSetOf<String>()
                var total = 0L
                for (i in 0 until records.length()) {
                    val record = records.getJSONObject(i)
                    val name = record.getString("path")
                    require(seen.add(name.lowercase())) { "同步包路径重复。" }
                    val destination = SyncFiles.path(folder, name)
                    val sizeValue = record.get("size")
                    require(sizeValue is Int || sizeValue is Long) { "同步文件大小必须为整数。" }
                    val size = record.getLong("size")
                    require(size >= 0 && size <= 512L * 1024 * 1024) { "同步文件大小无效。" }
                    total += size
                    require(total <= 512L * 1024 * 1024) { "单个同步项目超过 512 MiB。" }
                    Files.createDirectories(destination.parent)
                    if (name !in includedNames) {
                        require(name !in controlFiles && local != null && local.kind == description.getString("kind") && name in localPaths) { "同步包缺少文件：$name" }
                        val existing = SyncFiles.path(local.folder, name)
                        require(Files.size(existing) == size) { "本机同步文件大小不符：$name" }
                        SyncFiles.linkOrCopy(existing, destination)
                        continue
                    }
                    val entry = zip.getEntry("files/$name") ?: error("同步包缺少文件：$name")
                    require(entry.size == size) { "同步文件大小无效。" }
                    zip.getInputStream(entry).use { input -> Files.newOutputStream(destination).use { output ->
                        var count = 0L
                        val buffer = ByteArray(65536)
                        while (true) {
                            val n = input.read(buffer); if (n < 0) break
                            count += n; require(count <= size) { "同步文件解压大小不符。" }; output.write(buffer, 0, n)
                        }
                        require(count == size)
                    } }
                }
                require(included.all { it.lowercase() in seen }) { "同步包存在未登记文件。" }
                description
            }
            val kind = description.getString("kind")
            if (kind == "voice") {
                val names = SyncFiles.files(folder)
                require(names.size == 1 && '/' !in names.single()) { "声线包须只包含一个 WAV 文件。" }
                val file = SyncFiles.path(folder, names.single())
                val title = LocalVoiceStore.name(file)
                require(LocalVoiceStore.key(title) == description.getString("key") && title == description.getString("title")) { "声线身份与文件不符。" }
                val status = ArticleStore(data).withSyncLock { LocalVoiceStore(data).importFile(file, verifyContent = false) }
                entityIndex = null
                return JSONObject().put("status", status).put("key", description.getString("key")).put("kind", kind)
            }
            SyncFiles.validate(kind, folder, verifyContent = false)
            val incoming = entity(kind, folder)
            require(incoming.key == description.getString("key")) { "同步包身份与内容不符。" }
            val allowed = SyncFiles.allowed(kind, folder)
            require(SyncFiles.files(folder).toSet() == allowed) { "同步包包含不属于文库的文件。" }
            val status = if (kind == "article") ArticleStore(data).importSynced(folder, verifyContent = false)
            else ArticleStore(data).withSyncLock {
                recover()
                importOther(incoming)
            }
            entityIndex = null
            return JSONObject().put("status", status).put("key", incoming.key).put("kind", kind)
        } finally { SyncFiles.deleteTree(work) }
    }

    private fun entities(errors: JSONArray): List<Entity> {
        val found = linkedMapOf<String, Entity>()
        fun add(kind: String, folder: Path) {
            try {
                val item = entity(kind, folder)
                SyncFiles.allowed(kind, folder, allowMissingBookAssets = true)
                found.putIfAbsent(item.key, item)
            } catch (_: Exception) { errors.put("${folder.fileName}：文件缺失或校验失败，未同步。") }
        }
        directories(data.resolve("articles")).filter { Regex("\\d{4}-\\d{2}-\\d{2}").matches(it.fileName.toString()) }
            .forEach { day -> directories(day).forEach { add("article", it) } }
        directories(data.resolve("bookmarks")).filter { Files.exists(it.resolve("article.json")) }.forEach { add("article", it) }
        directories(data.resolve("books")).forEach { add("book", it) }
        directories(data.resolve("articles/examples")).forEach { add("example", it) }
        LocalVoiceStore(data).files().forEach { file ->
            try {
                val title = LocalVoiceStore.name(file)
                LocalVoiceStore.validate(file)
                require(file.fileName.toString() == "$title.wav") { "声线文件名须使用 NFC 名称与 .wav 后缀。" }
                val item = Entity("voice", LocalVoiceStore.key(title), title, file.parent)
                found.putIfAbsent(item.key, item)
            } catch (_: Exception) { errors.put("${file.fileName}：参考声线文件无效，未同步。") }
        }
        return found.values.toList()
    }

    private fun entity(kind: String, folder: Path): Entity = when (kind) {
        "article" -> {
            val meta = SyncFiles.json(SyncFiles.path(folder, "article.json"))
            require(meta.getInt("schema_version") == 1)
            val article = meta.getJSONObject("article")
            Entity(kind, SyncFiles.articleKey(article), article.getString("title"), folder)
        }
        "book" -> {
            val book = SyncFiles.json(SyncFiles.path(folder, "book.json"))
            require(book.getInt("version") == 2)
            val digest = book.getString("source_sha256")
            require(Regex("[0-9a-fA-F]{64}").matches(digest)) { "书籍缺少稳定同步身份。" }
            Entity(kind, "book:$digest", book.getJSONObject("book").getString("title"), folder, SyncFiles.chapterFeatures(folder, book))
        }
        else -> {
            val example = SyncFiles.json(SyncFiles.path(folder, "example.json"))
            require(example.getInt("schema_version") == 1)
            val title = example.getString("title").trim()
            Entity(kind, "example:${SyncFiles.hash(title.toByteArray(Charsets.UTF_8))}", title, folder)
        }
    }

    private fun importOther(incoming: Entity): String {
        val existing = indexedEntity(incoming.key)
        val targetRoot = data.resolve(if (incoming.kind == "book") "books" else "articles/examples")
        Files.createDirectories(targetRoot)
        val target = existing?.folder ?: allocate(targetRoot, incoming.title)
        val work = data.resolve("diagnostics/sync-transactions/${UUID.randomUUID()}")
        val stage = work.resolve("new")
        Files.createDirectories(stage)
        try {
            if (existing != null) SyncFiles.copyTree(target, stage, linkContents = true)
            val metaName = if (incoming.kind == "book") "book.json" else "example.json"
            val remote = SyncFiles.json(incoming.folder.resolve(metaName))
            val merged = if (existing == null) JSONObject(remote.toString()) else SyncFiles.json(target.resolve(metaName))
            if (existing != null && incoming.kind == "example" && Files.size(target.resolve("original.txt")) != Files.size(incoming.folder.resolve("original.txt"))) return "conflict"
            var changed = existing == null
            if (existing != null && incoming.kind == "book") {
                val localChapters = merged.getJSONObject("book").getJSONArray("chapters")
                val remoteChapters = remote.getJSONObject("book").getJSONArray("chapters")
                if (localChapters.length() != remoteChapters.length() || (0 until localChapters.length()).any {
                    localChapters.getJSONObject(it).getLong("id") != remoteChapters.getJSONObject(it).getLong("id")
                }) return "conflict"
            }
            for (name in SyncFiles.allowed(incoming.kind, incoming.folder)) {
                if (name == metaName || name == "state.json") continue
                if (existing != null && incoming.kind == "book" && name == remote.getString("source_file") && name != merged.getString("source_file")) continue
                val from = SyncFiles.path(incoming.folder, name)
                val to = SyncFiles.path(stage, name)
                if (Files.exists(to)) {
                    val chapterFile = incoming.kind == "book" && name.startsWith("chapters/") && name.endsWith(".json")
                    val missingFeatures = if (chapterFile) SyncFiles.missingChapterFeatures(incoming.chapterFeatures, existing?.chapterFeatures, name) else null
                    if (missingFeatures ?: (Files.size(from) != Files.size(to))) {
                        if (chapterFile) {
                            val before = SyncFiles.json(to)
                            val chapter = mergeChapter(before, SyncFiles.json(from)) ?: return "conflict"
                            if (chapter.second) {
                                SyncFiles.writeJson(to, chapter.first)
                                val chapters = merged.getJSONObject("book").getJSONArray("chapters")
                                for (i in 0 until chapters.length()) if (chapters.getJSONObject(i).getString("file") == name)
                                    chapters.getJSONObject(i).put("sha256", SyncFiles.hash(to))
                                changed = true
                            }
                        } else return "conflict"
                    }
                } else {
                    Files.createDirectories(to.parent); SyncFiles.linkOrCopy(from, to); changed = true
                    if (incoming.kind == "book") {
                        for (bucket in listOf("resources", "audio")) if (name.startsWith("$bucket/")) {
                            if (!merged.has(bucket)) merged.put(bucket, JSONObject())
                            val relative = name.removePrefix("$bucket/")
                            remote.optJSONObject(bucket)?.opt(relative)?.let { merged.getJSONObject(bucket).put(relative, it) }
                        }
                    }
                    if (incoming.kind == "example" && name == "translation.txt") {
                        remote.keys().asSequence().filter { it.startsWith("translation") }.forEach { merged.put(it, remote.get(it)) }
                    }
                }
            }
            if (incoming.kind == "example") {
                val versions = merged.optJSONArray("audio_versions") ?: JSONArray().also { merged.put("audio_versions", it) }
                val known = (0 until versions.length()).map { versions.getJSONObject(it).getString("path") }.toMutableSet()
                val newVersions = remote.optJSONArray("audio_versions") ?: JSONArray()
                for (i in 0 until newVersions.length()) {
                    val version = newVersions.getJSONObject(i)
                    if (known.add(version.getString("path"))) { versions.put(version); changed = true }
                }
            }
            if (!changed) return "unchanged"
            if (existing == null && incoming.kind == "book") {
                val usedIds = directories(targetRoot).mapNotNull { runCatching { SyncFiles.json(it.resolve("book.json")).getJSONObject("book").getLong("id") }.getOrNull() }
                merged.getJSONObject("book").put("id", (usedIds.maxOrNull() ?: 0L) + 1L)
                val state = SyncFiles.json(incoming.folder.resolve("state.json")).put("progress", JSONObject()).put("last_read_at", "")
                SyncFiles.writeJson(stage.resolve("state.json"), state)
            } else if (existing == null) {
                merged.put("id", "custom-${UUID.randomUUID().toString().replace("-", "")}")
            }
            SyncFiles.writeJson(stage.resolve(metaName), merged)
            SyncFiles.validate(incoming.kind, stage, verifyContent = false)
            commitDirectory(work, stage, target, existing != null)
            return if (existing == null) "created" else "updated"
        } finally { if (!Files.exists(work.resolve("journal.json"))) SyncFiles.deleteTree(work) }
    }

    private fun mergeChapter(local: JSONObject, remote: JSONObject): Pair<JSONObject, Boolean>? {
        if (local.getLong("id") != remote.getLong("id")) return null
        val blocks = local.optJSONArray("blocks") ?: JSONArray()
        val incoming = remote.optJSONArray("blocks") ?: JSONArray()
        if (blocks.length() != incoming.length()) return null
        var changed = copyMissing(local, remote, setOf("id", "blocks", "file", "sha256", "audio", "audio_versions"))
        for (i in 0 until blocks.length()) {
            val old = blocks.getJSONObject(i); val new = incoming.getJSONObject(i)
            if (old.optString("text_ja") != new.optString("text_ja")) return null
            if (old.optString("text_zh").isNotEmpty() && new.optString("text_zh").isNotEmpty() && old.getString("text_zh") != new.getString("text_zh")) return null
            if (copyMissing(old, new, setOf("id", "text_ja"))) changed = true
        }
        val remoteAudio = remote.optJSONObject("audio")
        if (local.optJSONObject("audio")?.optString("path").isNullOrBlank() && !remoteAudio?.optString("path").isNullOrBlank()) {
            local.put("audio", JSONObject(remoteAudio.toString())); changed = true
        }
        val versions = local.optJSONArray("audio_versions") ?: JSONArray()
        val knownAudio = (0 until versions.length()).mapNotNull { versions.optJSONObject(it)?.optString("path") }.toMutableSet()
        local.optJSONObject("audio")?.optString("path")?.takeIf { it.isNotBlank() }?.let(knownAudio::add)
        fun addAudio(version: JSONObject?) {
            val path = version?.optString("path")?.takeIf { it.isNotBlank() } ?: return
            if (knownAudio.add(path)) { versions.put(JSONObject(version.toString())); changed = true }
        }
        addAudio(remoteAudio)
        remote.optJSONArray("audio_versions")?.let { audio -> for (index in 0 until audio.length()) addAudio(audio.optJSONObject(index)) }
        if (versions.length() > 0) local.put("audio_versions", versions)
        return local to changed
    }

    private fun copyMissing(local: JSONObject, remote: JSONObject, excluded: Set<String>): Boolean {
        var changed = false
        fun empty(value: Any?): Boolean = value == null || value == JSONObject.NULL || value == "" || value is JSONArray && value.length() == 0 || value is JSONObject && value.length() == 0
        remote.keys().forEach { key ->
            if (key !in excluded && empty(local.opt(key)) && !empty(remote.opt(key))) { local.put(key, remote.get(key)); changed = true }
        }
        return changed
    }

    private fun allocate(root: Path, title: String): Path {
        val name = title.replace(Regex("[<>:\"/\\\\|?*\\x00-\\x1f]"), "_").trim().trimEnd(' ', '.').take(60).ifEmpty { "未命名" }
        var target = root.resolve(name)
        if (Files.exists(target)) target = root.resolve("$name--${UUID.randomUUID().toString().take(8)}")
        return target
    }

    private fun commitDirectory(work: Path, stage: Path, target: Path, replace: Boolean) {
        if (replace) SyncFiles.copyTree(target, data.resolve("backups/sync-${UUID.randomUUID()}/${target.fileName}"))
        SyncFiles.writeJson(work.resolve("journal.json"), JSONObject().put("target", data.toAbsolutePath().normalize().relativize(target.toAbsolutePath().normalize()).toString().replace('\\', '/')))
        if (replace) Files.move(target, work.resolve("old"))
        Files.move(stage, target)
        SyncFiles.deleteTree(work)
    }

    private fun recover() {
        directories(data.resolve("diagnostics/sync-transactions")).forEach { work ->
            if (!Files.isRegularFile(work.resolve("journal.json"))) return@forEach
            val name = SyncFiles.json(work.resolve("journal.json")).getString("target")
            require(name.startsWith("books/") || name.startsWith("articles/examples/"))
            val target = SyncFiles.path(data, name)
            if (!Files.exists(target)) {
                val old = work.resolve("old")
                if (Files.exists(old)) Files.move(old, target)
                else if (Files.exists(work.resolve("new"))) Files.move(work.resolve("new"), target)
                else error("同步恢复文件缺失。")
            }
            SyncFiles.deleteTree(work)
        }
    }

    private fun directories(root: Path): List<Path> = if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) emptyList()
        else Files.list(root).use { paths -> paths.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) }.collect(Collectors.toList()) }
}

internal object SyncFiles {
    fun missingChapterFeatures(source: JSONObject?, target: JSONObject?, name: String): Boolean? {
        val incoming = source?.optJSONArray(name) ?: return null
        val existing = target?.optJSONArray(name) ?: return null
        val known = (0 until existing.length()).map(existing::getString).toSet()
        return (0 until incoming.length()).any { incoming.getString(it) !in known }
    }

    fun chapterFeatures(folder: Path, meta: JSONObject): JSONObject {
        val result = JSONObject()
        val chapters = meta.getJSONObject("book").getJSONArray("chapters")
        for (i in 0 until chapters.length()) {
            val name = chapters.getJSONObject(i).getString("file")
            require(name.startsWith("chapters/"))
            if (!name.endsWith(".json")) continue
            val chapter = json(path(folder, name))
            val flags = mutableSetOf<String>()
            val blocks = chapter.optJSONArray("blocks") ?: JSONArray()
            for (index in 0 until blocks.length()) {
                val block = blocks.getJSONObject(index)
                if (block.optString("text_zh").isNotBlank()) flags += "zh:$index"
                if (block.optString("furigana_html").isNotBlank()) flags += "ruby:$index"
            }
            fun audio(value: JSONObject?) {
                value?.optString("path")?.takeIf { it.isNotBlank() }?.let { flags += "audio:$it" }
            }
            audio(chapter.optJSONObject("audio"))
            chapter.optJSONArray("audio_versions")?.let { versions ->
                for (index in 0 until versions.length()) audio(versions.optJSONObject(index))
            }
            result.put(name, JSONArray(flags.sorted()))
        }
        return result
    }

    fun articleKey(article: JSONObject): String {
        val key = article.optString("storage_key").ifEmpty {
            val url = article.optString("url")
            val day = article.optJSONArray("edition_dates")?.optString(0).orEmpty()
            require(url.isNotEmpty() && Regex("\\d{4}-\\d{2}-\\d{2}").matches(day)) { "文章缺少稳定同步身份。" }
            "edition:$day:$url"
        }
        return "article:$key"
    }

    fun path(root: Path, name: String): Path {
        val parts = name.split('/')
        require(parts.all { it.isNotEmpty() && it != "." && it != ".." && ':' !in it && '\\' !in it && it.none(Char::isISOControl) && !it.endsWith('.') && !it.endsWith(' ') }) { "同步路径无效。" }
        var cursor = root.toAbsolutePath().normalize()
        require(!Files.isSymbolicLink(cursor))
        parts.forEach { cursor = cursor.resolve(it); require(!Files.isSymbolicLink(cursor)) { "同步路径不能包含符号链接。" } }
        return cursor
    }

    fun files(root: Path): List<String> = Files.walk(root).use { paths -> paths.filter { it != root }.map {
        require(!Files.isSymbolicLink(it)) { "同步内容不能包含符号链接。" }; it
    }.filter { Files.isRegularFile(it, LinkOption.NOFOLLOW_LINKS) }.map { root.relativize(it).toString().replace('\\', '/') }.collect(Collectors.toList()) }

    fun allowed(kind: String, folder: Path, allowMissingBookAssets: Boolean = false): Set<String> {
        val result = mutableSetOf<String>()
        when (kind) {
            "article" -> {
                result += setOf("article.json", "original.txt", "translation.txt", "furigana.html")
                val assets = json(path(folder, "article.json")).optJSONArray("assets") ?: JSONArray()
                for (i in 0 until assets.length()) {
                    val name = assets.getJSONObject(i).getString("path")
                    require(name.startsWith("media/")); path(folder, name); result += name
                }
            }
            "book" -> {
                val meta = json(path(folder, "book.json"))
                result += setOf("book.json", "state.json", meta.getString("source_file"))
                val chapters = meta.getJSONObject("book").getJSONArray("chapters")
                for (i in 0 until chapters.length()) {
                    val name = chapters.getJSONObject(i).getString("file"); require(name.startsWith("chapters/")); result += name
                }
                meta.optJSONObject("resources")?.keys()?.forEach { result += "resources/$it" }
                meta.optJSONObject("audio")?.keys()?.forEach { if (completeAudio(it)) result += "audio/$it" }
            }
            "example" -> {
                result += setOf("example.json", "original.txt")
                if (Files.exists(path(folder, "translation.txt"))) result += "translation.txt"
            }
        }
        if (kind != "book" && Files.isDirectory(folder.resolve("audio"), LinkOption.NOFOLLOW_LINKS))
            files(folder.resolve("audio")).filter(::completeAudio).forEach { result += "audio/$it" }
        return result.filterTo(mutableSetOf()) { name ->
            val file = path(folder, name)
            // Keep the book's identity and advertise only files actually present, so a peer can fill missing images.
            if (allowMissingBookAssets && kind == "book" && (name.startsWith("resources/") || name.startsWith("audio/")) && !Files.exists(file, LinkOption.NOFOLLOW_LINKS)) false
            else { require(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) { "同步附件缺失：$name" }; true }
        }
    }

    fun validate(kind: String, folder: Path, verifyContent: Boolean = true) {
        allowed(kind, folder)
        when (kind) {
            "article" -> {
                val meta = json(path(folder, "article.json"))
                require(meta.getInt("schema_version") == 1)
                articleKey(meta.getJSONObject("article"))
                val specs = meta.getJSONObject("text_files")
                require(specs.keys().asSequence().toSet() == setOf("original.txt", "translation.txt", "furigana.html"))
                for (name in specs.keys()) {
                    val spec = specs.getJSONObject(name)
                    if (verifyContent) require(hash(path(folder, name)) == spec.getString("sha256")) { "文章正文或译文校验失败。" }
                    val text = String(Files.readAllBytes(path(folder, name)), Charsets.UTF_8)
                    if (name == "furigana.html") require(Jsoup.isValid(text,
                        Safelist.none().addTags("ruby", "rb", "rt", "rp", "span", "p", "br", "b", "strong", "i", "em", "u", "small", "sup", "sub")
                            .addAttributes(":all", "class", "lang"))) { "假名 HTML 含不安全内容，未同步。" }
                    val count = text.codePointCount(0, text.length)
                    val spans = spec.getJSONArray("paragraphs")
                    if (name == "original.txt") require(spans.length() > 0)
                    val allSpans = (0 until spans.length()).map { spans.getJSONArray(it) } +
                        if (spec.has("whole_field")) listOf(spec.getJSONArray("whole_span")) else emptyList()
                    allSpans.forEach { require(it.length() == 2 && it.getInt(0) >= 0 && it.getInt(1) >= it.getInt(0) && it.getInt(1) <= count) { "文章段落区间无效。" } }
                }
                val assets = meta.optJSONArray("assets") ?: JSONArray()
                for (i in 0 until assets.length()) {
                    val asset = assets.getJSONObject(i)
                    val file = path(folder, asset.getString("path"))
                    if (asset.has("bytes")) require(Files.size(file) == asset.getLong("bytes")) { "文章附件大小不符。" }
                    if (verifyContent) require(hash(file) == asset.getString("sha256")) { "文章附件校验失败。" }
                }
                val article = meta.getJSONObject("article")
                val registered = (0 until assets.length()).map { assets.getJSONObject(it).getString("path") }.toSet()
                for (field in listOf("image_paths", "video_urls")) article.optJSONArray(field)?.let { refs ->
                    for (i in 0 until refs.length()) {
                        val name = refs.getString(i)
                        if (!name.startsWith("http://") && !name.startsWith("https://")) require(name in registered)
                    }
                }
                val audio = article.optString("audio_path")
                if (audio.isNotEmpty()) {
                    require(audio.startsWith("audio/") && completeAudio(audio))
                    val file = path(folder, audio); require(Files.isRegularFile(file))
                    if (verifyContent && article.optString("audio_sha256").isNotEmpty()) require(hash(file) == article.getString("audio_sha256"))
                }
            }
            "book" -> {
                val meta = json(path(folder, "book.json")); require(meta.getInt("version") == 2)
                require(meta.getString("source_file").endsWith(".epub", true))
                if (verifyContent) require(hash(path(folder, meta.getString("source_file"))) == meta.getString("source_sha256")) { "原 EPUB 校验失败。" }
                val chapters = meta.getJSONObject("book").getJSONArray("chapters")
                for (i in 0 until chapters.length()) {
                    val chapter = chapters.getJSONObject(i)
                    if (verifyContent) require(hash(path(folder, chapter.getString("file"))) == chapter.getString("sha256")) { "书籍章节校验失败。" }
                }
                for (bucket in listOf("resources", "audio")) meta.optJSONObject(bucket)?.let { refs -> refs.keys().forEach { name ->
                    if (verifyContent && (bucket != "audio" || completeAudio(name))) require(hash(path(folder, "$bucket/$name")) == refs.getJSONObject(name).getString("sha256"))
                } }
                json(path(folder, "state.json"))
            }
            "example" -> {
                val meta = json(path(folder, "example.json")); require(meta.getInt("schema_version") == 1)
                if (verifyContent) require(hash(path(folder, "original.txt")) == meta.getString("text_sha256")) { "示例正文校验失败。" }
                if (verifyContent && meta.has("translation_sha256")) require(hash(path(folder, "translation.txt")) == meta.getString("translation_sha256"))
            }
        }
    }

    fun completeAudio(name: String): Boolean = (name.endsWith(".wav", true) || name.endsWith(".mp3", true)) &&
        "_segment_" !in name && ".part" !in name && ".tmp" !in name
    fun json(path: Path): JSONObject = JSONObject(String(Files.readAllBytes(path), Charsets.UTF_8))
    fun writeJson(path: Path, value: JSONObject) {
        // Staged content may share unchanged files through hard links. Replace before writing.
        Files.deleteIfExists(path)
        Files.write(path, value.toString().toByteArray(Charsets.UTF_8))
    }
    fun hash(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    fun hash(path: Path): String = Files.newInputStream(path).use { input ->
        val digest = MessageDigest.getInstance("SHA-256"); val buffer = ByteArray(65536)
        while (true) { val n = input.read(buffer); if (n < 0) break; digest.update(buffer, 0, n) }
        digest.digest().joinToString("") { "%02x".format(it) }
    }
    fun linkOrCopy(from: Path, to: Path) {
        try { Files.createLink(to, from) }
        catch (_: UnsupportedOperationException) { Files.copy(from, to) }
        catch (_: java.io.IOException) { Files.copy(from, to) }
    }
    fun copyTree(from: Path, to: Path, linkContents: Boolean = false) {
        Files.createDirectories(to)
        files(from).forEach { name ->
            val target = path(to, name); Files.createDirectories(target.parent)
            if (linkContents && name !in setOf("article.json", "book.json", "example.json", "state.json")) linkOrCopy(path(from, name), target)
            else Files.copy(path(from, name), target)
        }
    }
    fun deleteTree(root: Path) {
        if (!Files.exists(root, LinkOption.NOFOLLOW_LINKS)) return
        Files.walk(root).use { paths -> paths.sorted(Comparator.reverseOrder()).forEach(Files::delete) }
    }
}
