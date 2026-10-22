package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import java.nio.file.Files
import java.nio.file.Path

/** Matches PC's existing complete audio files without an audio registry or mobile synthesis. */
internal class SavedVoiceAudio(private val root: Path, private val settings: () -> JSONObject, private val browserVoices: () -> JSONArray) {
    data class Choice(val mode: String, val id: Long?, val name: String, val label: String, val sha: String = "", val savedOnly: Boolean = true) {
        val detail get() = "“$label”的完整朗读音频尚未同步，请先在 PC 生成后再同步；Android 不运行此声线的合成模型。"
    }
    fun choice(override: JSONObject? = null): Choice? {
        val mode = override ?: settings()
        if (mode.optString("mode") == "voice") {
            val id = mode.optLong("voice_id")
            val voice = LocalVoiceStore(root).find(id)
            val name = voice?.getString("name").orEmpty()
            val sha = if (name.isEmpty()) "" else SyncFiles.hash(root.resolve("voices/$name.wav"))
            return Choice("voice", id, name, name.ifEmpty { "所选参考声线" }, sha)
        }
        if (mode.optString("mode") == "browser") {
            val name = mode.optString("browser_voice_name")
            val catalog = browserVoices()
            val voice = (0 until catalog.length()).map { catalog.getJSONObject(it) }.firstOrNull { it.optString("id") == name }
            if (name in setOf("ja-JP-KeitaNeural", "ja-JP-NanamiNeural")) return Choice("browser", null, name,
                if (name == "ja-JP-KeitaNeural") "圭太" else "七海", savedOnly = false)
            if (name.isNotEmpty()) return Choice("browser", null, name, voice?.optString("name", name) ?: name)
        }
        return null
    }

    fun article(article: JSONObject, override: JSONObject? = null): JSONObject {
        val directory = "articles/${article.getString("_directory")}/audio"
        val audio = SyncFiles.path(root, directory)
        val current = article.optString("audio_path").removePrefix("audio/")
        fun readable(filename: String) = SyncFiles.completeAudio(filename) && runCatching {
            val file = SyncFiles.path(root, "$directory/$filename")
            Files.isRegularFile(file) && Files.size(file) > 0
        }.getOrDefault(false)
        if (override == null && current.isNotEmpty() && readable(current)) {
            article.put("audio_status", "ready").remove("audio_unavailable_detail")
            val mode = recordingMode(article, "audio_voice_id", "audio_voice_name")
            article.put("voice_mode", mode).put("audio_voice_mode", mode)
            if (!article.isNull("audio_voice_id")) {
                referenceName(article.optLong("audio_voice_id"))?.let { article.put("audio_voice_name", it) }
            }
            return article
        }
        if (override == null && (article.optString("source_voice_mode") == "none" || article.optString("audio_voice_mode") == "none")) return article
        val choice = choice(override) ?: return article
        val candidates = if (Files.isDirectory(audio) && !Files.isSymbolicLink(audio)) Files.list(audio).use {
            it.map { file -> file.fileName.toString() }.sorted().iterator().asSequence().toList()
        } else emptyList()
        val selected = candidates.firstOrNull { filename ->
            SyncFiles.completeAudio(filename) && (matches(filename, choice.label, article.getString("title")) ||
                filename == current && (article.optString("audio_voice_name") == choice.name && choice.name.isNotEmpty() ||
                    choice.mode == "voice" && !article.isNull("audio_voice_id") && article.optLong("audio_voice_id") == choice.id)) && readable(filename)
        }
        val keepSegments = selected != null && selected == current
        article.put("voice_mode", choice.mode).put("audio_voice_mode", choice.mode)
            .put("audio_voice_id", choice.id ?: JSONObject.NULL).put("audio_voice_name", choice.name)
            .put("audio_path", selected?.let { "audio/$it" } ?: "")
            .put("audio_status", if (selected != null) "ready" else if (choice.savedOnly) "unavailable" else "browser")
        if (!keepSegments) article.put("audio_segments", JSONArray())
        if (selected == null && choice.savedOnly) article.put("audio_unavailable_detail", choice.detail) else article.remove("audio_unavailable_detail")
        return article
    }

    fun chapter(chapter: JSONObject, override: JSONObject? = null, valid: (String) -> Boolean) {
        val candidates = mutableListOf<JSONObject>()
        chapter.optJSONObject("audio")?.let(candidates::add)
        val versions = chapter.optJSONArray("audio_versions") ?: JSONArray()
        for (i in 0 until versions.length()) versions.optJSONObject(i)?.let(candidates::add)
        val current = candidates.firstOrNull { SyncFiles.completeAudio(it.optString("path")) && valid(it.optString("path")) }
        if (override == null && current != null) {
            chapter.put("audio", current)
            current.put("status", "ready")
            chapter.remove("audio_unavailable_detail")
            chapter.put("voice_mode", recordingMode(current, "voice_id", "voice_name"))
            if (!current.isNull("voice_id")) {
                chapter.put("voice_id", current.getLong("voice_id"))
                referenceName(current.getLong("voice_id"))?.let { current.put("voice_name", it) }
            }
            return
        }
        val choice = choice(override) ?: return
        val audio = candidates.firstOrNull {
            val path = it.optString("path")
            SyncFiles.completeAudio(path) && (it.optString("voice_name") == choice.name && choice.name.isNotEmpty() ||
                choice.mode == "voice" && !it.isNull("voice_id") && it.optLong("voice_id") == choice.id ||
                choice.sha.isNotEmpty() && it.optString("voice_sha256") == choice.sha ||
                matches(path, choice.label, chapter.optString("title"), chapter.optLong("id"))) && valid(path)
        }
        chapter.put("voice_mode", choice.mode).put("voice_id", choice.id ?: JSONObject.NULL)
        if (audio == null) {
            chapter.put("audio", JSONObject().put("status", if (choice.savedOnly) "unavailable" else "browser").put("url", ""))
            if (choice.savedOnly) chapter.put("audio_unavailable_detail", choice.detail) else chapter.remove("audio_unavailable_detail")
        } else {
            chapter.put("audio", JSONObject(audio.toString()).put("status", "ready").put("voice_id", choice.id ?: JSONObject.NULL).put("voice_name", choice.name))
            chapter.remove("audio_unavailable_detail")
        }
    }

    private fun referenceName(id: Long): String? = runCatching { LocalVoiceStore(root).find(id)?.getString("name") }.getOrNull()
    private fun recordingMode(metadata: JSONObject, idField: String, nameField: String) =
        if (!metadata.isNull(idField) || metadata.optString(nameField).isEmpty()) "voice" else "browser"

    private fun matches(filename: String, voice: String, title: String, chapterId: Long? = null): Boolean {
        if (voice.isEmpty()) return false
        fun component(text: String) = text.replace(Regex("[<>:\"/\\\\|?*\\x00-\\x1f]+"), "_").replace(Regex("\\s+"), " ").trim(' ', '.', '_').ifEmpty { "未命名" }
        fun length(text: String) = text.codePointCount(0, text.length)
        fun take(text: String, limit: Int) = text.substring(0, text.offsetByCodePoints(0, minOf(length(text), limit)))
        val name = component(voice); val heading = component(title)
        var stem = "${name}_$heading"
        if (length(stem) + 4 > 42) {
            val marker = SyncFiles.hash("$name\u0000$heading".toByteArray(Charsets.UTF_8)).take(8)
            val remaining = 42 - 8 - 4 - 1
            val voiceLimit = minOf(length(name), maxOf(8, remaining / 2))
            val titleLimit = maxOf(8, remaining - voiceLimit - if (chapterId == null) 0 else 1)
            stem = "${take(name, voiceLimit)}_${take(heading, titleLimit)}-$marker"
        }
        val stems = mutableListOf(stem)
        if (chapterId != null) {
            val marker = SyncFiles.hash("$stem\u0000$chapterId".toByteArray(Charsets.UTF_8)).take(8)
            stems += "${take(stem, 42 - 8 - 4 - 1)}-$marker"
        }
        return stems.any { Regex("${Regex.escape(it)}(?:-[0-9a-fA-F]{8}(?:-[0-9]+)?)?\\.(?:wav|mp3)", RegexOption.IGNORE_CASE).matches(filename) }
    }
}
