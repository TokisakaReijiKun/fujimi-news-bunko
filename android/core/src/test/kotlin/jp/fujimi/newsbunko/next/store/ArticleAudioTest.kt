package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import jp.fujimi.newsbunko.next.speech.*
import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog

class ArticleAudioTest {
    @TempDir lateinit var data: Path

    @Test fun filenameUsesPcUnicodeWhitespaceAndCharacterLimit() {
        assertEquals("圭太_東京 ニュース.mp3", ArticleEdgeAudio.filename("東京　ニュース", EdgeVoiceCatalog.KEITA))
        val long = ArticleEdgeAudio.filename("😀".repeat(100), EdgeVoiceCatalog.NANAMI).removeSuffix(".mp3")
        assertEquals(92, long.codePointCount(0, long.length))
    }

    @Test fun syncedPcAudioUsesAnArticleScopedUrlWithoutRenamingItsFile() {
        val article = ArticleStore(data).create(JSONObject().put("title", "原稿")
            .put("url", "https://example.test/audio").put("paragraphs", JSONArray(listOf("今日は晴れ。"))), "2026-10-02")
        val folder = data.resolve(article.directory)
        val filename = "七海_原稿-元の名前.wav"
        Files.write(folder.resolve("audio/$filename"), byteArrayOf(1, 2, 3))
        val manifest = JSONObject(Files.readString(folder.resolve("article.json")))
        manifest.getJSONObject("article").put("audio_path", "audio/$filename").put("audio_status", "ready")
        Files.writeString(folder.resolve("article.json"), manifest.toString())
        val response = LocalLibraryApi(data).request("GET", "/api/articles/${article.metadata.getLong("id")}")
        assertEquals(200, response.status)
        assertEquals("/api/articles/${article.metadata.getLong("id")}/assets/audio/$filename",
            URI(JSONObject(response.body).getString("audio_path")).path)
        assertTrue(Files.exists(folder.resolve("audio/$filename")))
    }

    @Test fun completeSpeechPersistsThroughStoreAndCanBeReusedWithNoNetwork() {
        val original = create()
        val folder = data.resolve(original.directory)
        val sourceBytes = Files.readAllBytes(folder.resolve("original.txt"))
        val saved = ArticleEdgeAudio(data, { _, _ -> speech() }).generate(original.metadata.getLong("id"), EdgeVoiceCatalog.KEITA)
        assertFalse(saved.cached)
        assertEquals("audio/圭太_保存記事.mp3", saved.article.metadata.getString("audio_path"))
        assertArrayEquals(byteArrayOf(1, 2, 3, 4), Files.readAllBytes(folder.resolve("audio/圭太_保存記事.mp3")))
        assertArrayEquals(sourceBytes, Files.readAllBytes(folder.resolve("original.txt")))
        assertEquals(original.manifest.getJSONObject("text_files").toString(), saved.article.manifest.getJSONObject("text_files").toString())
        assertEquals(0, saved.article.manifest.getJSONArray("assets").length())
        val cached = ArticleEdgeAudio(data, { _, _ -> error("Network must not be used") })
            .generate(original.metadata.getLong("id"), EdgeVoiceCatalog.KEITA)
        assertTrue(cached.cached)
        assertEquals(saved.article.manifest.getInt("revision"), cached.article.manifest.getInt("revision"))
        assertFalse(Files.list(data.resolve("diagnostics")).use { paths -> paths.anyMatch { it.fileName.toString().startsWith("edge-complete-") } })
    }

    @Test fun changingVoiceAndFailurePreservePreviouslySavedAudio() {
        val article = create()
        val id = article.metadata.getLong("id")
        ArticleEdgeAudio(data, { _, _ -> speech() }).generate(id, EdgeVoiceCatalog.KEITA)
        assertThrows(IllegalStateException::class.java) {
            ArticleEdgeAudio(data, { _, _ -> error("Offline") }).generate(id, EdgeVoiceCatalog.NANAMI)
        }
        assertEquals(EdgeVoiceCatalog.KEITA, ArticleCatalog(data).find(id).metadata.getString("audio_voice_name"))
        ArticleEdgeAudio(data, { _, _ -> speech() }).generate(id, EdgeVoiceCatalog.NANAMI)
        assertTrue(Files.exists(data.resolve(article.directory).resolve("audio/圭太_保存記事.mp3")))
        assertTrue(Files.exists(data.resolve(article.directory).resolve("audio/七海_保存記事.mp3")))
    }

    @Test fun mismatchedParagraphTimingsAndChangedBodyCannotCommitAudio() {
        val article = create()
        val id = article.metadata.getLong("id")
        assertThrows(IllegalArgumentException::class.java) {
            ArticleEdgeAudio(data, { _, _ -> CompleteSpeech(byteArrayOf(1), JSONArray()) }).generate(id, EdgeVoiceCatalog.KEITA)
        }
        assertFalse(ArticleCatalog(data).find(id).metadata.has("audio_path"))
        val manifestFile = data.resolve(article.directory).resolve("article.json")
        val manifest = JSONObject(Files.readString(manifestFile))
        val span = manifest.getJSONObject("text_files").getJSONObject("original.txt").getJSONArray("paragraphs").getJSONArray(0)
        span.put(1, span.getInt(1) - 1)
        Files.writeString(manifestFile, manifest.toString())
        val audio = Files.createTempFile(data, "input-", ".mp3")
        Files.write(audio, byteArrayOf(1, 2, 3))
        assertThrows(IllegalArgumentException::class.java) {
            ArticleStore(data).saveAudio(article, EdgeVoiceCatalog.KEITA, "圭太_保存記事.mp3", audio, speech().segments)
        }
        assertFalse(Files.exists(data.resolve(article.directory).resolve("audio/圭太_保存記事.mp3")))
    }

    @Test fun audioAccessRejectsTraversalUnfinishedFilesAndOtherArticleFiles() {
        val article = create()
        val id = article.metadata.getLong("id")
        Files.write(data.resolve(article.directory).resolve("audio/未完成.tmp"), byteArrayOf(1))
        for (name in listOf("../original.txt", "../../../../diagnostics/secret.mp3", "未完成.tmp", "missing.mp3", "../audio/../original.txt")) {
            assertThrows(Exception::class.java) { ArticleAudioAccess(data).resolve(id, name) }
        }
    }

    @Test fun sentenceBoundariesMatchPcParagraphEdgesAndRejectMissingParagraphs() {
        val result = EdgeSentenceTimings.segments(listOf("今日は晴れ。", "明日は雨。"), listOf(
            SpeechBoundary("今日は晴れ。", 1_000_000, 10_000_000), SpeechBoundary("明日は雨。", 20_000_000, 10_000_000)))
        assertEquals(2.0, result.getJSONObject(0).getDouble("duration"))
        assertEquals(0.1, result.getJSONObject(0).getDouble("speech_start_offset"))
        assertEquals(1.0, result.getJSONObject(1).getDouble("duration"))
        assertThrows(IllegalArgumentException::class.java) {
            EdgeSentenceTimings.segments(listOf("今日は晴れ。", "明日は雨。"), listOf(SpeechBoundary("今日は晴れ。", 0, 1)))
        }
    }

    private fun create() = ArticleStore(data).create(JSONObject().put("title", "保存記事")
        .put("url", "https://example.test/saved").put("paragraphs", JSONArray(listOf("今日は晴れ。"))), "2026-10-02")

    private fun speech() = CompleteSpeech(byteArrayOf(1, 2, 3, 4), JSONArray().put(JSONObject()
        .put("duration", 1.0).put("speech_start_offset", 0.0).put("timing_source", "edge_sentence")))
}
