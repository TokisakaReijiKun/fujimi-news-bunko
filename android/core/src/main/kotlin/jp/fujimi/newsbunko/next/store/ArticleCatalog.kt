package jp.fujimi.newsbunko.next.store

import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.util.stream.Collectors

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

    fun find(id: Long): ArticleSnapshot {
        var found: ArticleSnapshot? = null
        for (day in days()) {
            for (article in onDay(day)) {
                if (article.metadata.getLong("id") != id) continue
                if (found != null) throw ArticleFormatException("不同文章使用了相同 ID：$id")
                found = article
            }
        }
        return found ?: throw NoSuchElementException("文章不存在：$id")
    }
}
