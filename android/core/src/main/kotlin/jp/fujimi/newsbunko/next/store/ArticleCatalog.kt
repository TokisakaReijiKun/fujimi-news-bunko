package jp.fujimi.newsbunko.next.store

import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.util.stream.Collectors
import org.json.JSONObject

/** Discovers day editions from the same directories used by the PC index rebuild. */
class ArticleCatalog(private val dataRoot: Path) {
    private val root = dataRoot.resolve("articles")
    private val reader = ArticleReader(dataRoot)
    private val dayPattern = Regex("\\d{4}-\\d{2}-\\d{2}")

    fun days(): List<String> {
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) return emptyList()
        return Files.list(root).use { items ->
            items.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) && dayPattern.matches(it.fileName.toString()) }
                .map { it.fileName.toString() }.sorted(Comparator.reverseOrder()).collect(Collectors.toList())
        }
    }

    fun onDay(day: String): List<ArticleSnapshot> {
        require(dayPattern.matches(day)) { "日刊日期格式无效。" }
        val directory = root.resolve(day)
        if (!Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS)) return emptyList()
        return Files.list(directory).use { folders ->
            folders.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) }
                .map { reader.load("articles/$day/${it.fileName}") }
                .sorted(Comparator.comparing { it.metadata.optString("created_at") })
                .collect(Collectors.toList())
        }
    }

    private fun dayDirectories(): List<String> = days().flatMap { day -> Files.list(root.resolve(day)).use { folders ->
            folders.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) }
                .map { "articles/$day/${it.fileName}" }.collect(Collectors.toList())
        } }

    fun find(id: Long): ArticleSnapshot {
        return findIn(id, dayDirectories()) ?: findBookmark(id)
    }

    fun findBookmark(id: Long): ArticleSnapshot = findIn(id, bookmarkDirectories())
        ?: findIn(id, legacyBookmarkDirectories())
        ?: throw NoSuchElementException("收藏文章不存在：$id")

    private fun declaredMetadata(directory: String): JSONObject? {
        val manifest = PreservedPathStore(dataRoot).resolveContentPath("$directory/article.json")
        var current = dataRoot.toAbsolutePath().normalize()
        for (part in current.relativize(manifest)) {
            current = current.resolve(part)
            if (Files.isSymbolicLink(current)) return null
        }
        if (!Files.isRegularFile(manifest, LinkOption.NOFOLLOW_LINKS)) return null
        return runCatching { JSONObject(String(Files.readAllBytes(manifest), Charsets.UTF_8)).getJSONObject("article") }.getOrNull()
    }

    // Older Android releases stored only the daily article's flag. Read it without migrating user files.
    private fun legacyBookmarkDirectories(): List<String> = dayDirectories().filter {
        declaredMetadata(it)?.optBoolean("bookmarked", false) == true
    }

    /** Identify candidates without making an unrelated article's body a dependency. */
    private fun findIn(id: Long, directories: List<String>): ArticleSnapshot? {
        var candidate: String? = null
        for (directory in directories) {
            val declaredId = declaredMetadata(directory)?.optLong("id", -1) ?: continue
            if (declaredId != id) continue
            if (candidate != null) throw ArticleFormatException("不同文章使用了相同 ID：$id")
            candidate = directory
        }
        // The selected article still receives the complete original/translation/attachment checks.
        return candidate?.let(reader::load)
    }

    fun bookmarks(): List<ArticleSnapshot> {
        val result = bookmarkDirectories().map(reader::load)
        if (result.map { it.metadata.getLong("id") }.distinct().size != result.size) throw ArticleFormatException("收藏文章ID重复。")
        val independentIds = result.map { it.metadata.getLong("id") }.toSet()
        val legacy = legacyBookmarkDirectories().filter { declaredMetadata(it)?.optLong("id", -1) !in independentIds }.map(reader::load)
        val combined = result + legacy
        if (combined.map { it.metadata.getLong("id") }.distinct().size != combined.size) throw ArticleFormatException("收藏文章ID重复。")
        return combined
    }

    private fun bookmarkDirectories(): List<String> {
        val folder = dataRoot.resolve("bookmarks")
        require(!Files.isSymbolicLink(folder)) { "收藏目录不能是符号链接。" }
        if (!Files.isDirectory(folder, LinkOption.NOFOLLOW_LINKS)) return emptyList()
        return Files.list(folder).use { paths -> paths.filter { Files.isDirectory(it, LinkOption.NOFOLLOW_LINKS) }
            .map { "bookmarks/${it.fileName}" }.collect(Collectors.toList()) }
    }
}
