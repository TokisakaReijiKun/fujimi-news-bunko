package jp.fujimi.newsbunko.next.store

import java.nio.file.Files
import java.nio.file.Path

/** PC audio files are owned by their article's audio directory and need no media registration. */
class ArticleAudioAccess(private val dataRoot: Path) {
    fun resolve(id: Long, name: String): Path {
        require(name.isNotBlank() && !name.startsWith('/') && '\\' !in name &&
            name.substringAfterLast('.').lowercase() in setOf("wav", "mp3")) { "音频文件名无效。" }
        val article = ArticleCatalog(dataRoot).find(id)
        val path = PreservedPathStore(dataRoot).resolveContentPath("${article.directory}/audio/$name")
        require(path.startsWith(dataRoot.toAbsolutePath().normalize().resolve(article.directory).resolve("audio"))) { "音频路径越过文章目录。" }
        var current = dataRoot.toAbsolutePath().normalize()
        for (part in current.relativize(path)) {
            current = current.resolve(part)
            require(!Files.isSymbolicLink(current)) { "音频路径含符号链接。" }
        }
        require(Files.isRegularFile(path) && Files.size(path) > 0) { "完整音频缺失。" }
        return path
    }
}
