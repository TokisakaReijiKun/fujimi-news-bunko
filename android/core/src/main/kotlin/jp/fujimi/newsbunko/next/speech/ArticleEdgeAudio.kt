package jp.fujimi.newsbunko.next.speech

import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog
import jp.fujimi.newsbunko.next.store.*
import org.json.JSONArray
import org.json.JSONObject
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest

data class CompleteSpeech(val audio: ByteArray, val segments: JSONArray)
data class SavedSpeech(val article: ArticleSnapshot, val cached: Boolean)

class ArticleEdgeAudio(private val data: Path, private val synthesize: (List<String>, String) -> CompleteSpeech,
                       private val validate: (Path) -> Unit = {}) {
    @Synchronized fun generate(id: Long, voice: String): SavedSpeech {
        require(voice in setOf(EdgeVoiceCatalog.KEITA, EdgeVoiceCatalog.NANAMI)) { "请选择圭太或七海。" }
        val article = ArticleCatalog(data).find(id)
        require(article.metadata.optString("status", "ready") == "ready") { "正文不可用，不能生成朗读。" }
        val segments = article.metadata.optJSONArray("audio_segments") ?: JSONArray()
        val existing = article.metadata.optString("audio_path")
        val textHash = article.manifest.getJSONObject("text_files").getJSONObject("original.txt").getString("sha256")
        if (article.metadata.optString("audio_voice_name") == voice && existing.startsWith("audio/") &&
            article.metadata.optString("audio_text_sha256", textHash) == textHash &&
            segments.length() == article.paragraphs.size && (0 until segments.length()).all {
                segments.getJSONObject(it).optString("timing_source") == "edge_sentence"
            }) {
            val path = try { ArticleAudioAccess(data).resolve(id, existing.removePrefix("audio/")) } catch (_: Exception) { null }
            if (path != null) {
                try {
                    val expected = article.metadata.optString("audio_sha256")
                    if (expected.isNotEmpty()) require(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)).joinToString("") { "%02x".format(it) } == expected)
                    validate(path)
                    return SavedSpeech(article, true)
                } catch (_: Exception) { }
            }
        }
        val generated = synthesize(article.paragraphs, voice)
        require(generated.audio.isNotEmpty() && generated.audio.size <= 8 * 1024 * 1024) { "完整音频为空或超过体积限制。" }
        val diagnostics = data.resolve("diagnostics")
        Files.createDirectories(diagnostics)
        val temporary = Files.createTempFile(diagnostics, "edge-complete-", ".mp3")
        try {
            Files.write(temporary, generated.audio)
            validate(temporary)
            val filename = filename(article.metadata.getString("title"), voice)
            var name = filename
            val folder = data.resolve(article.directory).resolve("audio")
            if (Files.exists(folder.resolve(name))) {
                val hash = MessageDigest.getInstance("SHA-256").digest(voice.toByteArray()).joinToString("") { "%02x".format(it) }.take(8)
                val stem = "${filename.removeSuffix(".mp3")}-$hash"
                name = "$stem.mp3"
                var number = 2
                while (Files.exists(folder.resolve(name))) name = "$stem-${number++}.mp3"
            }
            return SavedSpeech(ArticleStore(data).saveAudio(article, voice, name, temporary, generated.segments), false)
        } finally { Files.deleteIfExists(temporary) }
    }

    companion object {
        /** Same label/title cleaning and 92-character stem as PC /edge-tts. */
        fun filename(title: String, voice: String): String {
            val label = if (voice == EdgeVoiceCatalog.KEITA) "圭太" else "七海"
            val value = "${label}_$title".replace(Regex("[<>:\"/\\\\|?*\\x00-\\x1f]+"), "_")
                .replace(Regex("[\\s\\p{Z}\\u0085\\u001c-\\u001f]+"), " ").trim(' ', '.', '_').ifEmpty { "edge-tts" }
            return value.substring(0, value.offsetByCodePoints(0, minOf(92, value.codePointCount(0, value.length)))) + ".mp3"
        }
    }
}
