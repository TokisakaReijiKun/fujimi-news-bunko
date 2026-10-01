package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest

class ArticleFormatException(message: String, cause: Throwable? = null) : Exception(message, cause)

data class ArticleSnapshot(
    val metadata: JSONObject,
    val paragraphs: List<String>,
    val directory: String,
    val manifest: JSONObject,
)

/** Reads the file format written by the PC ArticleStore; SQLite is never a text fallback. */
class ArticleReader(private val dataRoot: Path) {
    fun load(relativeDirectory: String): ArticleSnapshot {
        val parts = relativeDirectory.split('/')
        if (parts.size != 3 || parts[0] != "articles" || !Regex("\\d{4}-\\d{2}-\\d{2}").matches(parts[1])) {
            throw ArticleFormatException("文章目录格式无效。")
        }
        val folder = PreservedPathStore(dataRoot).resolveContentPath("$relativeDirectory/article.json").parent
        try {
            var current = dataRoot.toAbsolutePath().normalize()
            for (segment in current.relativize(folder)) {
                current = current.resolve(segment)
                if (Files.isSymbolicLink(current)) throw ArticleFormatException("文章目录包含符号链接。")
            }
            val manifest = JSONObject(String(Files.readAllBytes(folder.resolve("article.json")), StandardCharsets.UTF_8))
            val article = JSONObject(manifest.getJSONObject("article").toString())
            if (manifest.getInt("schema_version") != 1 || article.getLong("id") <= 0L) {
                throw ArticleFormatException("不支持的文章文件格式。")
            }
            val files = manifest.getJSONObject("text_files")
            if (files.keys().asSequence().toSet() != setOf("original.txt", "translation.txt", "furigana.html")) {
                throw ArticleFormatException("文章缺少必要的文本文件描述。")
            }
            for (name in listOf("original.txt", "translation.txt", "furigana.html")) {
                val blob = Files.readAllBytes(folder.resolve(name))
                val spec = files.getJSONObject(name)
                if (sha256(blob) != spec.getString("sha256")) {
                    throw ArticleFormatException("$name 校验失败；原文或译文被外部修改。")
                }
                val text = String(blob, StandardCharsets.UTF_8)
                val spans = spec.getJSONArray("paragraphs")
                val pieces = JSONArray()
                for (index in 0 until spans.length()) pieces.put(portion(text, spans.getJSONArray(index)))
                article.put(spec.getString("field"), pieces)
                if (spec.has("whole_field")) {
                    article.put(spec.getString("whole_field"), portion(text, spec.getJSONArray("whole_span")))
                }
            }
            article.put("_revision", manifest.getInt("revision"))
            article.put("_directory", relativeDirectory.removePrefix("articles/"))
            val assets = manifest.optJSONArray("assets") ?: JSONArray()
            val registered = (0 until assets.length()).map { assets.getJSONObject(it).getString("path") }.toSet()
            for (path in localReferences(article)) {
                if (path !in registered) throw ArticleFormatException("文章引用了未登记的附件。")
            }
            val audioPath = article.optString("audio_path")
            if (audioPath.isNotEmpty() && (!audioPath.startsWith("audio/") ||
                !PreservedPathStore(dataRoot).resolveContentPath("$relativeDirectory/$audioPath").startsWith(folder.resolve("audio")))) {
                throw ArticleFormatException("音频必须位于文章 audio 目录。")
            }
            return ArticleSnapshot(article, jsonStrings(article.getJSONArray("paragraphs")), relativeDirectory, manifest)
        } catch (error: ArticleFormatException) {
            throw error
        } catch (error: Exception) {
            throw ArticleFormatException("文章文件缺失或格式无效：$relativeDirectory", error)
        }
    }

    private fun portion(text: String, span: JSONArray): String {
        if (span.length() != 2) throw ArticleFormatException("段落字符区间无效。")
        val start = span.getInt(0)
        val end = span.getInt(1)
        val count = text.codePointCount(0, text.length)
        if (start < 0 || end < start || end > count) throw ArticleFormatException("段落字符区间无效。")
        val left = text.offsetByCodePoints(0, start)
        val right = text.offsetByCodePoints(0, end)
        return text.substring(left, right)
    }

    private fun localReferences(article: JSONObject): List<String> {
        val images = jsonStrings(article.optJSONArray("image_paths") ?: JSONArray())
        val videos = jsonStrings(article.optJSONArray("video_urls") ?: JSONArray())
            .filterNot { it.startsWith("http://") || it.startsWith("https://") }
        return images + videos
    }

    private fun jsonStrings(array: JSONArray): List<String> =
        (0 until array.length()).map { array.getString(it) }

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }
}
