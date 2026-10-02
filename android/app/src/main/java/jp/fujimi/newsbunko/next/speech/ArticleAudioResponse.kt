package jp.fujimi.newsbunko.next.speech

import android.webkit.WebResourceResponse
import jp.fujimi.newsbunko.next.store.ArticleAudioAccess
import java.io.FileInputStream
import java.io.FilterInputStream
import java.nio.file.Files
import java.nio.file.Path

/** Stream saved article audio, including the byte ranges used when seeking. */
class ArticleAudioResponse(private val data: Path) {
    fun open(id: Long, name: String, range: String?): WebResourceResponse {
        val path = ArticleAudioAccess(data).resolve(id, name)
        val size = Files.size(path)
        val headers = mutableMapOf("Accept-Ranges" to "bytes", "Cache-Control" to "no-store", "X-Content-Type-Options" to "nosniff")
        var start = 0L
        var end = size - 1
        if (range != null) {
            val match = Regex("bytes=(\\d*)-(\\d*)").matchEntire(range)
            if (match == null || match.groupValues.drop(1).all { it.isEmpty() }) return invalidRange(size)
            if (match.groupValues[1].isEmpty()) {
                val suffix = match.groupValues[2].toLongOrNull() ?: return invalidRange(size)
                if (suffix <= 0) return invalidRange(size)
                start = maxOf(0, size - suffix)
            } else {
                start = match.groupValues[1].toLongOrNull() ?: return invalidRange(size)
                if (match.groupValues[2].isNotEmpty()) end = minOf(end, match.groupValues[2].toLongOrNull() ?: return invalidRange(size))
            }
            if (start > end || start >= size) return invalidRange(size)
            headers["Content-Range"] = "bytes $start-$end/$size"
        }
        val length = end - start + 1
        headers["Content-Length"] = length.toString()
        val file = FileInputStream(path.toFile())
        file.channel.position(start)
        val stream = object : FilterInputStream(file) {
            var remaining = length
            override fun read(): Int {
                if (remaining == 0L) return -1
                val value = super.read()
                if (value >= 0) remaining--
                return value
            }
            override fun read(buffer: ByteArray, offset: Int, count: Int): Int {
                if (count == 0) return 0
                if (remaining == 0L) return -1
                val result = `in`.read(buffer, offset, minOf(count.toLong(), remaining).toInt())
                if (result > 0) remaining -= result
                return result
            }
        }
        return WebResourceResponse(if (name.endsWith(".wav", true)) "audio/wav" else "audio/mpeg", null,
            if (range == null) 200 else 206, if (range == null) "OK" else "Partial Content", headers, stream)
    }

    private fun invalidRange(size: Long) = WebResourceResponse("text/plain", "UTF-8", 416, "Range Not Satisfiable",
        mapOf("Content-Range" to "bytes */$size"), ByteArray(0).inputStream())
}
