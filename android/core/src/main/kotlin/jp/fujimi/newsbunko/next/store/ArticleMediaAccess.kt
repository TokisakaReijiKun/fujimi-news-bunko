package jp.fujimi.newsbunko.next.store

import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest

/** Resolve only manifest-registered media, and verify bytes before streaming to WebView. */
class ArticleMediaAccess(private val dataRoot: Path) {
    fun resolve(articleId: Long, relativeName: String, bookmarkContext: Boolean = false): Path {
        require(relativeName.isNotBlank() && !relativeName.startsWith('/') && '\\' !in relativeName)
        val catalog = ArticleCatalog(dataRoot)
        val article = if (bookmarkContext) catalog.findBookmark(articleId) else catalog.find(articleId)
        val name = "media/$relativeName"
        val assets = article.manifest.getJSONArray("assets")
        val asset = (0 until assets.length()).map { assets.getJSONObject(it) }.firstOrNull { it.getString("path") == name }
            ?: throw NoSuchElementException("文章未登记此媒体。")
        val path = PreservedPathStore(dataRoot).resolveContentPath("${article.directory}/$name")
        var current = dataRoot.toAbsolutePath().normalize()
        for (segment in current.relativize(path)) {
            current = current.resolve(segment)
            require(!Files.isSymbolicLink(current)) { "附件路径含符号链接。" }
        }
        require(Files.isRegularFile(path) && Files.size(path) == asset.getLong("bytes")) { "附件缺失或大小不匹配。" }
        val digest = MessageDigest.getInstance("SHA-256")
        Files.newInputStream(path).use { input ->
            val buffer = ByteArray(65536)
            while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
        }
        require(digest.digest().joinToString("") { "%02x".format(it) } == asset.getString("sha256")) { "附件校验失败。" }
        return path
    }
}
