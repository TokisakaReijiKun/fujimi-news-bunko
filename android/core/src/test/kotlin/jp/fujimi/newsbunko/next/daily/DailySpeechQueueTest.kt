package jp.fujimi.newsbunko.next.daily

import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.util.concurrent.CancellationException

class DailySpeechQueueTest {
    private val article = JSONObject().put("id", 11).put("title", "新闻").put("source_voice_mode", "browser")
    private val reference = JSONObject().put("mode", "voice").put("voice_id", 7).put("browser_voice_name", EdgeVoiceCatalog.NANAMI)

    @Test fun offlineReferenceGeneratesKeitaWithoutChangingTheSelectedVoice() {
        val queue = DailySpeechQueue(listOf(article), reference, false)
        assertTrue(queue.fallback)
        assertTrue(queue.advance({ _, _, _ -> fail("No PC") }, { id, voice ->
            assertEquals(11L, id); assertEquals(EdgeVoiceCatalog.KEITA, voice)
        }, { fail("No upload while offline") }, {}))
        assertTrue(queue.finished)
        assertEquals("voice", reference.getString("mode"))
        assertEquals(7, reference.getInt("voice_id"))
    }

    @Test fun connectedReferenceWaitsForPcBeforeCountingAudioAndDoesNotStartDuplicateJob() {
        val queue = DailySpeechQueue(listOf(article), reference, true)
        var calls = 0
        val remote = { id: Long, mode: JSONObject, task: String? ->
            assertEquals(11L, id); assertEquals(7, mode.getInt("voice_id"))
            calls++
            if (calls == 1) { assertNull(task); JSONObject().put("status", "queued").put("task_id", "one") }
            else { assertEquals("one", task); JSONObject().put("status", "ready") }
        }
        assertFalse(queue.advance(remote, { _, _ -> fail("PC must synthesize") }, {}, {}))
        assertEquals(0, queue.progress().getInt("audio_completed"))
        assertTrue(queue.advance(remote, { _, _ -> fail("PC must synthesize") }, {}, {}))
        assertTrue(queue.finished)
        assertEquals(1, queue.progress().getInt("audio_completed"))
    }

    @Test fun connectedPhoneVoiceUploadsItsCompletedAudioAndPcFailureDoesNotFallback() {
        val edge = DailySpeechQueue(listOf(article), JSONObject().put("mode", "browser").put("browser_voice_name", EdgeVoiceCatalog.NANAMI), true)
        val events = mutableListOf<String>()
        edge.advance({ _, _, _ -> fail("Phone voice") }, { _, voice -> events.add(voice) }, { events.add("upload") }, {})
        assertEquals(listOf(EdgeVoiceCatalog.NANAMI, "upload"), events)
        val pc = DailySpeechQueue(listOf(article), reference, true)
        pc.advance({ _, _, _ -> JSONObject().put("status", "failed").put("detail", "模型失败") }, { _, _ -> fail("No hidden fallback") }, {}, {})
        assertEquals(1, pc.errors.length())
        assertEquals(0, pc.progress().getInt("audio_completed"))
    }

    @Test fun disabledSourcesStaySilentAndCancellationIsNotAnAudioError() {
        val disabled = DailySpeechQueue(listOf(JSONObject(article.toString()).put("source_voice_mode", "none")), reference, true)
        assertTrue(disabled.finished)
        val queue = DailySpeechQueue(listOf(article), reference, false)
        assertThrows(CancellationException::class.java) {
            queue.advance({ _, _, _ -> JSONObject() }, { _, _ -> throw CancellationException() }, {}, {})
        }
        assertEquals(0, queue.errors.length())
    }
}
