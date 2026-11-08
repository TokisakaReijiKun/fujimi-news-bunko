package jp.fujimi.newsbunko.next.speech

import android.content.Context
import android.media.AudioAttributes
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import org.json.JSONObject
import java.util.ArrayDeque
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/** Japanese speech through the engine selected in Android's text-to-speech settings. */
class SystemSpeechPlayer(context: Context, private val event: (String, String) -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    private val initialized = CountDownLatch(1)
    private val generation = AtomicLong()
    private var engine: TextToSpeech? = null
    @Volatile private var available = false
    @Volatile private var closed = false
    private var activeId: String? = null
    private var chunkId = ""
    private var started = false
    private var rate = 1f
    private val pending = ArrayDeque<String>()

    init {
        main.post {
            if (closed) return@post
            try {
                engine = TextToSpeech(context.applicationContext) { result ->
                    main.post {
                        if (closed) return@post
                        val tts = engine
                        try {
                            if (result == TextToSpeech.SUCCESS && tts != null) {
                                available = tts.setLanguage(Locale.JAPAN) >= TextToSpeech.LANG_AVAILABLE
                                tts.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                                tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                                    override fun onStart(id: String?) = dispatch(id) {
                                        if (!started) { started = true; activeId?.let { event(it, "start") } }
                                    }
                                    override fun onDone(id: String?) = dispatch(id) { next() }
                                    @Deprecated("Legacy engine callback")
                                    override fun onError(id: String?) = dispatch(id) { finish("error") }
                                    override fun onError(id: String?, code: Int) = dispatch(id) { finish("error") }
                                    override fun onStop(id: String?, interrupted: Boolean) = dispatch(id) { finish("stop") }
                                })
                            }
                        } finally { initialized.countDown() }
                    }
                }
            } catch (_: Exception) { initialized.countDown() }
        }
    }

    private fun ready(): Boolean {
        if (Looper.myLooper() != Looper.getMainLooper()) initialized.await(4, TimeUnit.SECONDS)
        return available && !closed
    }

    fun voice(): JSONObject = JSONObject().put("id", ID).put("name", "システム音声")
        .put("lang", "ja-JP").put("provider", "android").put("available", ready())
        .put("read_only", true).put("saved_audio_only", false).put("local", false)
        .put("unavailable_detail", "手机的文字转语音引擎尚未提供日语音声，请在系统设置中启用。")

    fun speak(text: String, speed: Float, id: String, cancelled: () -> Boolean = { false }) {
        check(ready()) { "手机的文字转语音引擎尚未提供日语音声，请在系统设置中启用。" }
        if (cancelled()) { event(id, "stop"); return }
        require(text.isNotBlank() && text.length <= 200000) { "朗读文本为空或过长。" }
        val token = generation.incrementAndGet()
        val chunks = mutableListOf<String>()
        val current = StringBuilder()
        val limit = minOf(3500, TextToSpeech.getMaxSpeechInputLength())
        text.codePoints().toArray().forEach { point ->
            val chars = Character.toChars(point)
            if (current.length + chars.size > limit) { chunks.add(current.toString()); current.clear() }
            current.append(chars)
        }
        if (current.isNotEmpty()) chunks.add(current.toString())
        main.post {
            if (closed || generation.get() != token || cancelled()) { event(id, "stop"); return@post }
            finish("stop")
            engine?.stop()
            activeId = id; rate = speed.coerceIn(.5f, 2f); started = false
            pending.addAll(chunks); next()
        }
    }

    private fun dispatch(id: String?, action: () -> Unit) {
        main.post { if (!closed && id == chunkId && activeId != null) action() }
    }

    private fun next() {
        val id = activeId ?: return
        val text = pending.pollFirst() ?: return finish("done")
        chunkId = "$id:${generation.get()}:${pending.size}"
        try {
            val tts = engine ?: return finish("error")
            if (tts.setSpeechRate(rate) != TextToSpeech.SUCCESS ||
                tts.speak(text, TextToSpeech.QUEUE_FLUSH, Bundle(), chunkId) != TextToSpeech.SUCCESS) finish("error")
        } catch (_: Exception) { finish("error") }
    }

    private fun finish(result: String) {
        val id = activeId
        activeId = null; chunkId = ""; pending.clear()
        if (id != null) event(id, result)
    }

    fun stop() {
        generation.incrementAndGet()
        main.post { finish("stop"); engine?.stop() }
    }

    fun close() {
        closed = true; generation.incrementAndGet(); initialized.countDown()
        main.post { finish("stop"); engine?.stop(); engine?.shutdown(); engine = null }
    }

    companion object { const val ID = "android:system" }
}
