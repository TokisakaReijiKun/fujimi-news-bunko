package jp.fujimi.newsbunko.next.store

import jp.fujimi.newsbunko.next.daily.StoredMedia
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.security.MessageDigest
import java.time.LocalDate
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.locks.ReentrantLock
import java.util.stream.Collectors
import kotlin.concurrent.withLock

/** Creates the PC file format. Files are authoritative; Android requires no SQLite text cache. */
class ArticleStore(dataRoot: Path) {
    private val data = dataRoot.toAbsolutePath().normalize()
    private val transactions = data.resolve("diagnostics/transactions")
    private val lock = locks.computeIfAbsent(data.toString()) { ReentrantLock() }

    fun create(
        article: JSONObject,
        day: String,
        media: List<StoredMedia> = emptyList(),
        checkpoint: () -> Unit = {},
    ): ArticleSnapshot = locked {
        checkpoint()
        LocalDate.parse(day)
        val original = strings(article.optJSONArray("paragraphs") ?: JSONArray())
        require(original.isNotEmpty() && original.all { it.isNotBlank() }) { "文章没有有效正文。" }
        for (field in listOf("translated_paragraphs", "furigana_paragraphs")) {
            val parts = article.optJSONArray(field) ?: JSONArray()
            require(parts.length() == 0 || parts.length() == original.size) { "$field 段落数与原文不一致。" }
            strings(parts)
        }
        val title = article.getString("title")
        require(title.isNotBlank()) { "文章缺少标题。" }
        val url = article.optString("url")
        val existing = ArticleCatalog(data).onDay(day).firstOrNull {
            url.isNotEmpty() && it.metadata.optString("url") == url
        }
        if (existing != null) return@locked existing
        media.forEach(::validateMedia)
        require(media.map { it.path }.distinct().size == media.size) { "附件路径重复。" }
        val id = allocateId()
        val relative = allocateDirectory(title, id, day)
        val target = contentDirectory(relative)
        val metadata = JSONObject(article.toString())
            .put("id", id).put("edition_dates", JSONArray(listOf(day))).put("bookmarked", false)
            .put("storage_key", if (url.isNotEmpty()) "edition:$day:$url" else "local:${UUID.randomUUID().toString().replace("-", "")}")
        if (!metadata.has("created_at")) metadata.put("created_at", "${day}T00:00:00+08:00")
        if (!metadata.has("status")) metadata.put("status", "ready")
        val transaction = transactions.resolve(UUID.randomUUID().toString().replace("-", ""))
        val stage = transaction.resolve("new")
        safeDirectories(stage)
        try {
            checkpoint()
            safeDirectories(stage.resolve("media"))
            safeDirectories(stage.resolve("audio"))
            val specs = JSONObject()
            for ((filename, field, whole) in listOf(
                Triple("original.txt", "paragraphs", "original_text"),
                Triple("translation.txt", "translated_paragraphs", "full_translation"),
                Triple("furigana.html", "furigana_paragraphs", null),
            )) {
                val (bytes, spec) = textFile(metadata, field, whole)
                durableWrite(stage.resolve(filename), bytes)
                specs.put(filename, spec)
            }
            val assets = JSONArray()
            for (asset in media) {
                checkpoint()
                val path = stage.resolve(asset.path)
                safeDirectories(path.parent)
                durableWrite(path, asset.bytes)
                assets.put(JSONObject().put("path", asset.path).put("kind", asset.kind)
                    .put("caption", asset.caption).put("position", asset.paragraphIndex)
                    .put("source_url", asset.sourceUrl).put("sha256", sha256(asset.bytes)).put("bytes", asset.bytes.size))
            }
            validateReferences(metadata, media.map { it.path }.toSet())
            metadata.keys().asSequence().toList().filter { it in textFields || it.startsWith("_") }
                .forEach { metadata.remove(it) }
            val manifestBytes = JSONObject().put("schema_version", 1).put("revision", 1)
                .put("article", metadata).put("text_files", specs).put("assets", assets).toString().toByteArray(Charsets.UTF_8)
            durableWrite(stage.resolve("article.json"), manifestBytes)
            checkpoint()
            durableWrite(transaction.resolve("journal.json"), JSONObject().put("target", relative.removePrefix("articles/"))
                .put("article_id", id).put("manifest_sha256", sha256(manifestBytes))
                .toString().toByteArray(Charsets.UTF_8))
            safeDirectories(target.parent)
            require(!Files.exists(target, LinkOption.NOFOLLOW_LINKS)) { "目标文章目录已存在，未覆盖。" }
            checkpoint()
            moveNew(stage, target)
            val result = ArticleReader(data).load(relative)
            deleteTree(transaction)
            result
        } catch (error: Exception) {
            // A directory already switched into place remains authoritative and its journal recoverable.
            if (Files.exists(stage) || !Files.exists(transaction.resolve("journal.json"))) deleteTree(transaction)
            throw error
        }
    }

    fun recover() = locked { Unit }

    /** Shares the existing file lock with synchronisation of PC-format book and example folders. */
    fun <T> withSyncLock(work: () -> T): T = locked(work)

    /** Merge validated files through the ordinary recoverable article directory transaction. */
    fun importSynced(source: Path, verifyContent: Boolean = true): String = locked {
        SyncFiles.validate("article", source, verifyContent)
        val remote = SyncFiles.json(source.resolve("article.json"))
        val remoteArticle = remote.getJSONObject("article")
        val key = SyncFiles.articleKey(remoteArticle)
        val existingDirectory = syncArticleMetadata().firstOrNull { SyncFiles.articleKey(it.second) == key }?.first
        val existing = existingDirectory?.let { ArticleReader(data, verifyContent).load(it) }
        if (existing != null && Files.size(data.resolve(existing.directory).resolve("original.txt")) != Files.size(source.resolve("original.txt"))) return@locked "conflict"
        val day = remoteArticle.optJSONArray("edition_dates")?.optString(0).orEmpty()
        LocalDate.parse(day)
        val id = existing?.metadata?.getLong("id") ?: allocateId(verifyContent)
        val relative = existing?.directory ?: allocateDirectory(remoteArticle.getString("title"), id, day)
        val target = contentDirectory(relative)
        val transaction = transactions.resolve(UUID.randomUUID().toString().replace("-", ""))
        val stage = transaction.resolve("new")
        safeDirectories(stage)
        try {
            if (existing != null) SyncFiles.copyTree(target, stage, linkContents = true)
            val merged = if (existing == null) JSONObject(remote.toString()) else JSONObject(existing.manifest.toString())
            val article = merged.getJSONObject("article")
            article.put("id", id).put("storage_key", key.removePrefix("article:"))
            if (existing == null) { article.put("progress", JSONObject()).put("last_read_at", "") }
            var changed = existing == null
            val oldBookmarked = article.optBoolean("bookmarked")
            article.put("bookmarked", oldBookmarked || remoteArticle.optBoolean("bookmarked"))
            if (oldBookmarked != article.optBoolean("bookmarked")) changed = true
            val textSpecs = merged.getJSONObject("text_files")
            for (name in SyncFiles.allowed("article", source)) {
                if (name == "article.json") continue
                val from = SyncFiles.path(source, name)
                val to = SyncFiles.path(stage, name)
                if (Files.exists(to)) {
                    if (Files.size(from) == Files.size(to)) continue
                    if (name in setOf("translation.txt", "furigana.html")) {
                        val currentSpec = textSpecs.getJSONObject(name)
                        val incomingSpec = remote.getJSONObject("text_files").getJSONObject(name)
                        if (currentSpec.getJSONArray("paragraphs").length() == 0 && incomingSpec.getJSONArray("paragraphs").length() > 0) {
                            Files.copy(from, to, StandardCopyOption.REPLACE_EXISTING)
                            textSpecs.put(name, incomingSpec); changed = true; continue
                        }
                        // Independent valid translations stay local; neither side silently overwrites them.
                        if (incomingSpec.getJSONArray("paragraphs").length() == 0) continue
                        val currentParts = syncParagraphs(to, currentSpec)
                        val incomingParts = syncParagraphs(from, incomingSpec)
                        if (currentParts.size != incomingParts.size || currentParts.indices.any {
                            currentParts[it].isNotBlank() && incomingParts[it].isNotBlank() && currentParts[it] != incomingParts[it]
                        }) return@locked "conflict"
                        val combined = currentParts.indices.map { currentParts[it].ifBlank { incomingParts[it] } }
                        if (combined != currentParts) {
                            val field = currentSpec.getString("field")
                            val (bytes, spec) = textFile(JSONObject().put(field, JSONArray(combined)), field, currentSpec.optString("whole_field").ifEmpty { null })
                            Files.delete(to); Files.write(to, bytes); textSpecs.put(name, spec); changed = true
                        }
                        continue
                    }
                    return@locked "conflict"
                }
                safeDirectories(to.parent); SyncFiles.linkOrCopy(from, to); changed = true
            }
            val assets = merged.optJSONArray("assets") ?: JSONArray().also { merged.put("assets", it) }
            val knownAssets = (0 until assets.length()).map { assets.getJSONObject(it).getString("path") }.toMutableSet()
            val remoteAssets = remote.optJSONArray("assets") ?: JSONArray()
            for (i in 0 until remoteAssets.length()) {
                val asset = remoteAssets.getJSONObject(i)
                if (knownAssets.add(asset.getString("path"))) { assets.put(asset); changed = true }
            }
            for (field in listOf("image_paths", "video_urls")) {
                val values = article.optJSONArray(field) ?: JSONArray()
                val known = strings(values).toMutableSet()
                val incoming = remoteArticle.optJSONArray(field) ?: JSONArray()
                for (i in 0 until incoming.length()) {
                    val value = incoming.getString(i)
                    if (known.add(value)) { values.put(value); changed = true }
                }
                if (values.length() > 0) article.put(field, values)
            }
            if (article.optString("audio_path").isEmpty() && remoteArticle.optString("audio_path").isNotEmpty()) {
                remoteArticle.keys().asSequence().filter { it.startsWith("audio_") }.forEach { article.put(it, remoteArticle.get(it)) }
                changed = true
            }
            if (!changed) {
                if (article.optBoolean("bookmarked")) saveSyncedBookmark(target, article, verifyContent)
                return@locked "unchanged"
            }
            merged.put("revision", (existing?.manifest?.optInt("revision") ?: 0) + 1)
            val manifestBytes = merged.toString().toByteArray(Charsets.UTF_8)
            Files.deleteIfExists(stage.resolve("article.json"))
            durableWrite(stage.resolve("article.json"), manifestBytes)
            SyncFiles.validate("article", stage, verifyContent)
            if (existing != null) SyncFiles.copyTree(target, data.resolve("backups/sync-${UUID.randomUUID()}/${target.fileName}"))
            durableWrite(transaction.resolve("journal.json"), JSONObject().put("target", relative.removePrefix("articles/"))
                .put("article_id", id).put("manifest_sha256", sha256(manifestBytes)).toString().toByteArray(Charsets.UTF_8))
            safeDirectories(target.parent)
            if (existing != null) moveNew(target, transaction.resolve("old"))
            moveNew(stage, target)
            ArticleReader(data, verifyContent).load(relative)
            deleteTree(transaction)
            if (article.optBoolean("bookmarked")) saveSyncedBookmark(target, article, verifyContent)
            if (existing == null) "created" else "updated"
        } finally { if (!Files.exists(transaction.resolve("journal.json"))) deleteTree(transaction) }
    }

    private fun syncParagraphs(path: Path, spec: JSONObject): List<String> {
        val text = String(Files.readAllBytes(path), Charsets.UTF_8)
        val spans = spec.getJSONArray("paragraphs")
        return (0 until spans.length()).map {
            val span = spans.getJSONArray(it)
            text.substring(text.offsetByCodePoints(0, span.getInt(0)), text.offsetByCodePoints(0, span.getInt(1)))
        }
    }

    private fun saveSyncedBookmark(source: Path, article: JSONObject, verifyContent: Boolean = true) {
        val root = data.resolve("bookmarks")
        safeDirectories(root)
        val key = SyncFiles.articleKey(article)
        val existing = Files.list(root).use { paths -> paths.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) }
            .filter { runCatching { SyncFiles.articleKey(SyncFiles.json(it.resolve("article.json")).getJSONObject("article")) == key }.getOrDefault(false) }
            .findFirst().orElse(null) }
        var target = existing ?: root.resolve(source.fileName)
        if (existing == null && Files.exists(target)) target = root.resolve("${source.fileName}--${article.getLong("id")}")
        if (existing != null && SyncFiles.files(source).toSet() == SyncFiles.files(existing).toSet() &&
            SyncFiles.files(source).all {
                if (verifyContent) SyncFiles.hash(source.resolve(it)) == SyncFiles.hash(existing.resolve(it))
                else Files.size(source.resolve(it)) == Files.size(existing.resolve(it))
            }) return
        val transaction = transactions.resolve(UUID.randomUUID().toString().replace("-", ""))
        val stage = transaction.resolve("new")
        SyncFiles.copyTree(source, stage)
        if (existing != null) SyncFiles.copyTree(existing, data.resolve("backups/sync-${UUID.randomUUID()}/${existing.fileName}"))
        durableWrite(transaction.resolve("journal.json"), JSONObject().put("target_root", "bookmarks").put("target", target.fileName.toString())
            .put("article_id", article.getLong("id")).put("manifest_sha256", SyncFiles.hash(stage.resolve("article.json")))
            .toString().toByteArray(Charsets.UTF_8))
        if (existing != null) moveNew(existing, transaction.resolve("old"))
        moveNew(stage, target)
        deleteTree(transaction)
    }

    /** Keep the daily copy and independent bookmark copy recoverable as one requested change. */
    fun setBookmarked(id: Long, enabled: Boolean) = locked {
        val current = ArticleCatalog(data).find(id)
        val target = contentDirectory(current.directory)
        if (current.directory.startsWith("bookmarks/")) {
            if (!enabled) removeBookmark(current.metadata)
            return@locked
        }
        if (current.metadata.optBoolean("bookmarked") == enabled) {
            reconcileBookmark(target, current.metadata)
            return@locked
        }
        val transaction = transactions.resolve(UUID.randomUUID().toString().replace("-", ""))
        val stage = transaction.resolve("new")
        try {
            SyncFiles.copyTree(target, stage)
            Files.delete(stage.resolve("article.json"))
            val manifest = JSONObject(current.manifest.toString()).put("revision", current.manifest.getInt("revision") + 1)
            manifest.getJSONObject("article").put("bookmarked", enabled)
            val bytes = manifest.toString().toByteArray(Charsets.UTF_8)
            durableWrite(stage.resolve("article.json"), bytes)
            durableWrite(transaction.resolve("journal.json"), JSONObject().put("target", current.directory.removePrefix("articles/"))
                .put("article_id", id).put("manifest_sha256", sha256(bytes)).put("bookmark_action", enabled).toString().toByteArray(Charsets.UTF_8))
            moveNew(target, transaction.resolve("old")); moveNew(stage, target)
            val saved = ArticleReader(data).load(current.directory)
            reconcileBookmark(target, saved.metadata)
            deleteTree(transaction)
        } catch (failure: Exception) {
            if (!Files.exists(transaction.resolve("journal.json"))) deleteTree(transaction)
            throw failure
        }
    }

    private fun reconcileBookmark(source: Path, article: JSONObject) {
        if (article.optBoolean("bookmarked")) saveSyncedBookmark(source, article) else removeBookmark(article)
    }

    private fun removeBookmark(article: JSONObject) {
        val bookmarks = data.resolve("bookmarks")
        if (!Files.isDirectory(bookmarks, LinkOption.NOFOLLOW_LINKS)) return
        ensureNoSymlinks(bookmarks)
        val key = SyncFiles.articleKey(article)
        val targets = Files.list(bookmarks).use { paths -> paths.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) }
            .filter { SyncFiles.articleKey(SyncFiles.json(it.resolve("article.json")).getJSONObject("article")) == key }
            .collect(Collectors.toList()) }
        for (target in targets) {
            val transaction = transactions.resolve(UUID.randomUUID().toString().replace("-", ""))
            safeDirectories(transaction)
            durableWrite(transaction.resolve("journal.json"), JSONObject().put("target_root", "bookmarks").put("target", target.fileName.toString())
                .put("article_id", article.getLong("id")).put("delete", true).toString().toByteArray(Charsets.UTF_8))
            moveNew(target, transaction.resolve("old")); deleteTree(transaction)
        }
    }

    /** Commit complete TTS through the same recoverable directory transaction as article files. */
    fun saveAudio(source: ArticleSnapshot, voice: String, filename: String, audio: Path, segments: JSONArray): ArticleSnapshot = locked {
        val current = ArticleCatalog(data).find(source.metadata.getLong("id"))
        require(current.directory == source.directory && current.paragraphs == source.paragraphs &&
            current.manifest.getJSONObject("text_files").getJSONObject("original.txt").getString("sha256") ==
            source.manifest.getJSONObject("text_files").getJSONObject("original.txt").getString("sha256")) {
            "正文版本已变更，音频未保存，请重新生成。"
        }
        require(filename.endsWith(".mp3") && filename.none { it in "/\\:" || it.isISOControl() }) { "音频文件名无效。" }
        require(Files.isRegularFile(audio) && Files.size(audio) > 0) { "完整音频缺失。" }
        require(segments.length() == current.paragraphs.size) { "音频段落时间与正文不一致。" }
        for (index in 0 until segments.length()) {
            val segment = segments.getJSONObject(index)
            require(segment.getDouble("duration").isFinite() && segment.getDouble("duration") > 0 &&
                segment.optDouble("speech_start_offset", 0.0).isFinite() && segment.optDouble("speech_start_offset", 0.0) >= 0) { "音频段落时间无效。" }
        }
        val target = contentDirectory(current.directory)
        val relative = "audio/$filename"
        require(!Files.exists(target.resolve(relative), LinkOption.NOFOLLOW_LINKS)) { "音频文件已存在，未覆盖。" }
        val transaction = transactions.resolve(UUID.randomUUID().toString().replace("-", ""))
        val stage = transaction.resolve("new")
        safeDirectories(stage)
        try {
            Files.walk(target).use { paths -> paths.forEach { file ->
                require(!Files.isSymbolicLink(file)) { "文章附件不能是符号链接。" }
                val destination = stage.resolve(target.relativize(file))
                if (Files.isDirectory(file, LinkOption.NOFOLLOW_LINKS)) safeDirectories(destination)
                else if (file != target.resolve("article.json")) Files.copy(file, destination)
            } }
            safeDirectories(stage.resolve("audio"))
            Files.newInputStream(audio).use { input ->
                FileChannel.open(stage.resolve(relative), StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE).use { channel ->
                    val buffer = ByteArray(65536)
                    while (true) {
                        val count = input.read(buffer); if (count < 0) break
                        val bytes = ByteBuffer.wrap(buffer, 0, count)
                        while (bytes.hasRemaining()) channel.write(bytes)
                    }
                    channel.force(true)
                }
            }
            val manifest = JSONObject(current.manifest.toString()).put("revision", current.manifest.getInt("revision") + 1)
            manifest.getJSONObject("article").put("audio_path", relative).put("audio_segments", segments)
                .put("audio_status", "ready").put("audio_voice_mode", "browser").put("audio_voice_id", JSONObject.NULL)
                .put("audio_voice_name", voice)
                .put("audio_text_sha256", current.manifest.getJSONObject("text_files").getJSONObject("original.txt").getString("sha256"))
                .put("audio_sha256", sha256(Files.readAllBytes(stage.resolve(relative))))
            val bytes = manifest.toString().toByteArray(Charsets.UTF_8)
            durableWrite(stage.resolve("article.json"), bytes)
            durableWrite(transaction.resolve("journal.json"), JSONObject().put("target", current.directory.removePrefix("articles/"))
                .put("article_id", current.metadata.getLong("id")).put("manifest_sha256", sha256(bytes)).toString().toByteArray(Charsets.UTF_8))
            moveNew(target, transaction.resolve("old"))
            moveNew(stage, target)
            val saved = ArticleReader(data).load(current.directory)
            deleteTree(transaction)
            saved
        } catch (failure: Exception) {
            if (!Files.exists(transaction.resolve("journal.json"))) deleteTree(transaction)
            throw failure
        }
    }

    /** SQLite and imported PC content may have a higher historical sequence than active files. */
    fun advanceSequenceFloor(nextId: Long): Long = locked {
        require(nextId > 0) { "文章序号下限必须是正整数。" }
        val actual = maxOf(nextId, currentSequence(), knownNextId())
        persistSequence(actual)
        actual
    }

    private fun <T> locked(work: () -> T): T = lock.withLock {
        safeDirectories(transactions)
        safeDirectories(data.resolve("backups"))
        val lockFile = transactions.resolve(".lock")
        require(!Files.isSymbolicLink(lockFile)) { "存储锁不能是符号链接。" }
        FileChannel.open(lockFile, StandardOpenOption.CREATE, StandardOpenOption.READ, StandardOpenOption.WRITE).use { channel ->
            if (channel.size() == 0L) channel.write(ByteBuffer.wrap(byteArrayOf(48)))
            channel.lock(0, 1, false).use {
                recoverTransactions()
                work()
            }
        }
    }

    private fun recoverTransactions() {
        Files.list(transactions).use { entries ->
            entries.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) }.forEach { transaction ->
                val journal = transaction.resolve("journal.json")
                if (!Files.exists(journal, LinkOption.NOFOLLOW_LINKS)) return@forEach
                require(!Files.isSymbolicLink(journal)) { "事务日志不能是符号链接。" }
                val record = JSONObject(readUtf8(journal))
                val relative = "${record.optString("target_root", "articles")}/${record.getString("target")}"
                val target = contentDirectory(relative)
                val stage = transaction.resolve("new")
                val old = transaction.resolve("old")
                require(!Files.isSymbolicLink(stage) && !Files.isSymbolicLink(old)) { "文章事务不能包含符号链接。" }
                if (record.optBoolean("delete")) {
                    require(relative.startsWith("bookmarks/")) { "删除事务仅限收藏副本。" }
                    if (Files.exists(old, LinkOption.NOFOLLOW_LINKS)) verifyRecoveryIdentity(record, old)
                    if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
                        verifyRecoveryIdentity(record, target)
                        deleteTree(target)
                    }
                    deleteTree(transaction)
                    return@forEach
                }
                when {
                    Files.exists(stage, LinkOption.NOFOLLOW_LINKS) -> {
                        if (Files.exists(old, LinkOption.NOFOLLOW_LINKS) && !Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
                            verifyRecoveryIdentity(record, old)
                            safeDirectories(target.parent)
                            moveNew(old, target)
                            validateRecoveryFolder(relative)
                        } else if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
                            validateRecoveryFolder(relative)
                            verifyRecoveryIdentity(record, target)
                            if (Files.exists(old, LinkOption.NOFOLLOW_LINKS) && manifestId(old) != manifestId(target)) {
                                throw ArticleFormatException("恢复目标属于另一篇文章，保留事务和旧版本。")
                            }
                        }
                    }
                    Files.exists(target, LinkOption.NOFOLLOW_LINKS) -> {
                        validateRecoveryFolder(relative)
                        verifyRecoveryIdentity(record, target)
                        if (record.has("manifest_sha256") && sha256(Files.readAllBytes(target.resolve("article.json"))) != record.getString("manifest_sha256")) {
                            throw ArticleFormatException("已提交文章与事务记录不一致，保留恢复日志。")
                        }
                        if (Files.exists(old, LinkOption.NOFOLLOW_LINKS) && manifestId(old) != manifestId(target)) {
                            throw ArticleFormatException("恢复目标属于另一篇文章，保留事务和旧版本。")
                        }
                    }
                    Files.exists(old, LinkOption.NOFOLLOW_LINKS) -> {
                        verifyRecoveryIdentity(record, old)
                        safeDirectories(target.parent)
                        moveNew(old, target)
                        validateRecoveryFolder(relative)
                    }
                    else -> throw ArticleFormatException("无法恢复文章事务：${transaction.fileName}")
                }
                if (record.has("bookmark_action")) reconcileBookmark(target, SyncFiles.json(target.resolve("article.json")).getJSONObject("article"))
                deleteTree(transaction)
            }
        }
    }

    private fun verifyRecoveryIdentity(record: JSONObject, folder: Path) {
        val id = manifestId(folder)
        if (record.has("article_id") && record.getLong("article_id") != id) {
            throw ArticleFormatException("恢复目标属于另一篇文章，保留事务和旧版本。")
        }
    }

    private fun validateRecoveryFolder(relative: String) {
        if (relative.startsWith("bookmarks/")) SyncFiles.validate("article", contentDirectory(relative))
        else ArticleReader(data).load(relative)
    }

    private fun manifestId(folder: Path): Long {
        try {
            val file = folder.resolve("article.json")
            require(!Files.isSymbolicLink(file)) { "文章清单不能是符号链接。" }
            val manifest = JSONObject(readUtf8(file))
            require(manifest.getInt("schema_version") == 1)
            return manifest.getJSONObject("article").getLong("id").also { require(it > 0) }
        } catch (error: Exception) {
            throw ArticleFormatException("无法验证恢复文章身份，保留事务日志。", error)
        }
    }

    private fun syncArticleMetadata(): List<Pair<String, JSONObject>> = ArticleCatalog(data).days().flatMap { day ->
        Files.list(data.resolve("articles/$day")).use { folders ->
            folders.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) }.map { folder ->
                val name = "articles/$day/${folder.fileName}"
                name to SyncFiles.json(SyncFiles.path(data, "$name/article.json")).getJSONObject("article")
            }.collect(Collectors.toList())
        }
    }

    private fun allocateId(verifyContent: Boolean = true): Long {
        val known = if (verifyContent) knownNextId() else Math.addExact(syncArticleMetadata().maxOfOrNull { it.second.getLong("id") } ?: 0L, 1L)
        val next = maxOf(currentSequence(), known)
        require(next > 0) { "文章序号无效。" }
        persistSequence(Math.addExact(next, 1L))
        return next
    }

    private fun knownNextId(): Long {
        val known = ArticleCatalog(data).days().flatMap { ArticleCatalog(data).onDay(it) }
            .maxOfOrNull { it.metadata.getLong("id") } ?: 0L
        return Math.addExact(known, 1L)
    }

    private fun currentSequence(): Long {
        val sequence = data.resolve("diagnostics/article-sequence.json")
        require(!Files.isSymbolicLink(sequence)) { "文章序号不能是符号链接。" }
        return (if (Files.exists(sequence)) JSONObject(readUtf8(sequence)).getLong("next_id") else 1L)
            .also { require(it > 0) { "文章序号无效。" } }
    }

    private fun persistSequence(next: Long) {
        val sequence = data.resolve("diagnostics/article-sequence.json")
        val temporary = sequence.resolveSibling("article-sequence-${UUID.randomUUID()}.tmp")
        try {
            durableWrite(temporary, JSONObject().put("next_id", next).toString().toByteArray(Charsets.UTF_8))
            try { Files.move(temporary, sequence, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING) }
            catch (_: AtomicMoveNotSupportedException) { Files.move(temporary, sequence, StandardCopyOption.REPLACE_EXISTING) }
        } finally { Files.deleteIfExists(temporary) }
    }

    private fun allocateDirectory(title: String, id: Long, day: String): String {
        val folder = data.resolve("articles/$day")
        ensureNoSymlinks(folder)
        val maximum = minOf(65, 225 - codePoints(folder.toString()) - 45)
        require(maximum >= 12) { "数据根目录路径过长，请使用较短的文库目录。" }
        var name = title.replace(Regex("[<>:\"/\\\\|?*\\x00-\\x1f]"), "_").trim().trimEnd(' ', '.')
            .ifEmpty { "未命名文章" }
        if (Regex("^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\\.|$)", RegexOption.IGNORE_CASE).containsMatchIn(name)) name = "_$name"
        val suffix = "--$id"
        if (codePoints(name) > maximum) name = prefix(name, maximum - suffix.length).trimEnd(' ', '.') + suffix
        val existing = if (Files.isDirectory(folder, LinkOption.NOFOLLOW_LINKS)) Files.list(folder).use { entries ->
            entries.map { it.fileName.toString().lowercase(Locale.ROOT) }.collect(Collectors.toList()).toSet()
        } else emptySet()
        if (name.lowercase(Locale.ROOT) in existing) name = prefix(name, maximum - suffix.length).trimEnd(' ', '.') + suffix
        require(name.lowercase(Locale.ROOT) !in existing) { "文章目录发生冲突，未覆盖现有文件。" }
        return "articles/$day/$name"
    }

    private fun contentDirectory(relative: String): Path {
        val parts = relative.split('/')
        require(parts.size == 3 && parts[0] == "articles" || parts.size == 2 && parts[0] == "bookmarks") { "文章事务目录格式无效。" }
        if (parts[0] == "articles") LocalDate.parse(parts[1])
        val target = PreservedPathStore(data).resolveContentPath("$relative/article.json").parent
        ensureNoSymlinks(target)
        return target
    }

    private fun validateMedia(media: StoredMedia) {
        val parts = media.path.split('/')
        require(parts.size >= 2 && parts[0] == "media" && parts.all {
            it.isNotBlank() && it != "." && it != ".." && ':' !in it && '\\' !in it && '\u0000' !in it
        }) { "附件必须位于文章 media 目录。" }
        require(media.kind in setOf("image", "video") && media.bytes.isNotEmpty()) { "附件内容或类型无效。" }
        require(media.paragraphIndex >= -1) { "附件段落位置无效。" }
    }

    private fun validateReferences(article: JSONObject, registered: Set<String>) {
        val references = strings(article.optJSONArray("image_paths") ?: JSONArray()) +
            strings(article.optJSONArray("video_urls") ?: JSONArray()).filterNot { it.startsWith("https://") || it.startsWith("http://") }
        require(references.all { it in registered }) { "文章引用了未登记附件。" }
        require(article.optString("audio_path").isEmpty()) { "创建新闻不能登记已有音频路径。" }
    }

    private fun textFile(article: JSONObject, field: String, whole: String?): Pair<ByteArray, JSONObject> {
        val parts = strings(article.optJSONArray(field) ?: JSONArray())
        var text = ""
        val spans = JSONArray()
        parts.forEachIndexed { index, part ->
            if (index > 0) text += "\n\n"
            val start = codePoints(text)
            text += part
            spans.put(JSONArray(listOf(start, codePoints(text))))
        }
        val spec = JSONObject().put("field", field).put("paragraphs", spans)
        if (whole != null) {
            val full = if (article.has(whole)) article.getString(whole) else text
            var charStart = text.indexOf(full)
            if (charStart < 0) { text += "\n\n"; charStart = text.length; text += full }
            val start = codePoints(text.substring(0, charStart))
            spec.put("whole_field", whole).put("whole_span", JSONArray(listOf(start, start + codePoints(full))))
        }
        val bytes = text.toByteArray(Charsets.UTF_8)
        spec.put("sha256", sha256(bytes))
        return bytes to spec
    }

    private fun safeDirectories(path: Path) {
        ensureNoSymlinks(path)
        Files.createDirectories(path)
        ensureNoSymlinks(path)
    }

    private fun ensureNoSymlinks(path: Path) {
        require(path.toAbsolutePath().normalize().startsWith(data)) { "存储路径越过文库目录。" }
        var current = data
        require(!Files.isSymbolicLink(current)) { "文库根目录不能是符号链接。" }
        for (part in data.relativize(path)) {
            current = current.resolve(part)
            require(!Files.isSymbolicLink(current)) { "存储路径包含符号链接。" }
        }
    }

    private fun durableWrite(path: Path, bytes: ByteArray) {
        FileChannel.open(path, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE).use { channel ->
            val buffer = ByteBuffer.wrap(bytes)
            while (buffer.hasRemaining()) channel.write(buffer)
            channel.force(true)
        }
    }

    private fun moveNew(source: Path, target: Path) {
        // No REPLACE_EXISTING: an unexpected target is a conflict, never permission to overwrite.
        Files.move(source, target)
    }

    private fun deleteTree(path: Path) {
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return
        Files.walk(path).use { paths -> paths.sorted(Comparator.reverseOrder()).forEach(Files::delete) }
    }

    private fun codePoints(text: String) = text.codePointCount(0, text.length)
    private fun prefix(text: String, count: Int) = text.substring(0, text.offsetByCodePoints(0, minOf(count, codePoints(text))))
    private fun strings(array: JSONArray) = (0 until array.length()).map { array.getString(it) }
    private fun readUtf8(path: Path) = String(Files.readAllBytes(path), Charsets.UTF_8)
    private fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    companion object {
        private val locks = ConcurrentHashMap<String, ReentrantLock>()
        private val textFields = setOf("paragraphs", "translated_paragraphs", "furigana_paragraphs", "original_text", "full_translation")
    }
}
