package jp.fujimi.newsbunko.next

import android.content.Context
import android.media.MediaPlayer
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import jp.fujimi.newsbunko.next.speech.ArticleEdgeAudio
import jp.fujimi.newsbunko.next.speech.EdgeSpeechPlayer
import jp.fujimi.newsbunko.next.speech.ArticleAudioResponse
import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog
import jp.fujimi.newsbunko.next.store.ArticleStore
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Explicit live Edge verification, selected separately from the offline device test suite. */
@RunWith(AndroidJUnit4::class)
class EdgeAudioDeviceTest {
    @Test fun bothVoicesGenerateSavedMp3AndSavedAudioPlaysWithoutSynthesis() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val temporary = Files.createTempDirectory(context.cacheDir.toPath(), "saved-speech-")
        val speech = EdgeSpeechPlayer(context) { _, _ -> }
        try {
            val article = ArticleStore(temporary).create(JSONObject().put("title", "朗読の保存確認")
                .put("url", "https://example.test/saved-audio").put("paragraphs", JSONArray(listOf("今日は晴れです。", "「A&B」という名前も読みます。"))), "2026-10-02")
            val id = article.metadata.getLong("id")
            val service = ArticleEdgeAudio(temporary, speech::completeArticle, speech::validateFile)
            val keita = service.generate(id, EdgeVoiceCatalog.KEITA)
            assertFalse(keita.cached)
            assertEquals(2, keita.article.metadata.getJSONArray("audio_segments").length())
            val nanami = service.generate(id, EdgeVoiceCatalog.NANAMI)
            assertFalse(nanami.cached)
            val path = temporary.resolve(article.directory).resolve(nanami.article.metadata.getString("audio_path"))
            val bytes = Files.readAllBytes(path)
            assertTrue(bytes.size > 1000)
            assertTrue(Files.exists(temporary.resolve(article.directory).resolve(keita.article.metadata.getString("audio_path"))))
            val offline = ArticleEdgeAudio(temporary, { _, _ -> error("Network disabled for offline reuse") }, speech::validateFile)
            assertTrue(offline.generate(id, EdgeVoiceCatalog.NANAMI).cached)
            val name = path.fileName.toString()
            val response = ArticleAudioResponse(temporary).open(id, name, "bytes=10-29")
            assertEquals(206, response.statusCode)
            assertArrayEquals(bytes.copyOfRange(10, 30), response.data.use { it.readBytes() })
            val completed = CountDownLatch(1)
            val player = MediaPlayer()
            try {
                player.setOnCompletionListener { completed.countDown() }
                player.setDataSource(path.toString())
                player.prepare()
                assertTrue(player.duration > 0)
                player.start()
                assertTrue("Saved MP3 did not finish playing", completed.await(30, TimeUnit.SECONDS))
            } finally { player.release() }
            assertArrayEquals(bytes, Files.readAllBytes(path))
        } finally { speech.close(); temporary.toFile().deleteRecursively() }
    }

    @Test fun longParagraphAcrossRequestsKeepsCompleteAudioAndParagraphTimings() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val speech = EdgeSpeechPlayer(context) { _, _ -> }
        val temporary = Files.createTempFile(context.cacheDir.toPath(), "long-speech-", ".mp3")
        try {
            val paragraphs = listOf("これは長い段落の朗読です。".repeat(100), "二つ目の段落も保存します。")
            assertTrue(paragraphs.joinToString("\n").toByteArray().size > 3500)
            val complete = speech.completeArticle(paragraphs, EdgeVoiceCatalog.KEITA)
            Files.write(temporary, complete.audio)
            speech.validateFile(temporary)
            assertEquals(2, complete.segments.length())
            assertTrue(complete.segments.getJSONObject(0).getDouble("duration") > 60)
            assertTrue(complete.segments.getJSONObject(1).getDouble("duration") > 0)
        } finally { speech.close(); Files.deleteIfExists(temporary) }
    }
}
