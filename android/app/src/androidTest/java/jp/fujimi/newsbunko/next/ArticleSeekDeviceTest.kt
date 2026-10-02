package jp.fujimi.newsbunko.next

import android.content.Context
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.DefaultAudioSink
import androidx.media3.exoplayer.audio.TeeAudioProcessor
import androidx.test.core.app.ApplicationProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import jp.fujimi.newsbunko.next.speech.ArticleMediaPlayer
import jp.fujimi.newsbunko.next.store.ArticleStore
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files

/** Inspect actual decoded PCM after forward/backward seeks, not the progress label. */
@RunWith(AndroidJUnit4::class)
@androidx.annotation.OptIn(markerClass = [UnstableApi::class])
class ArticleSeekDeviceTest {
    private class Tones : TeeAudioProcessor.AudioBufferSink {
        @Volatile var frequency = 0.0
        @Volatile var epoch = 0
        private var sampleRate = 0
        private var channels = 0
        private var encoding = 0
        override fun flush(sampleRateHz: Int, channelCount: Int, encoding: Int) {
            sampleRate = sampleRateHz; channels = channelCount; this.encoding = encoding
            frequency = 0.0; epoch++
        }
        override fun handleBuffer(buffer: ByteBuffer) {
            if (encoding != C.ENCODING_PCM_16BIT || channels < 1) return
            val pcm = buffer.duplicate().order(ByteOrder.LITTLE_ENDIAN)
            var crossings = 0; var previous = 0; var samples = 0; var amplitude = 0
            while (pcm.remaining() >= channels * 2) {
                val value = pcm.short.toInt()
                if (samples > 0 && (value >= 0) != (previous >= 0)) crossings++
                previous = value; amplitude = maxOf(amplitude, kotlin.math.abs(value)); samples++
                pcm.position(pcm.position() + (channels - 1) * 2)
            }
            if (samples > 500 && amplitude > 1000) frequency = crossings * sampleRate.toDouble() / (2 * samples)
        }
    }

    @Test fun savedMp3SeeksDecodeTheRequestedParagraphAndDoNotModifyAudio() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val temporary = Files.createTempDirectory(context.cacheDir.toPath(), "paragraph-seek-")
        var media: ArticleMediaPlayer? = null
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        try {
            val article = ArticleStore(temporary).create(JSONObject().put("title", "音声位置の一時検証")
                .put("url", "https://example.test/paragraph-seek").put("paragraphs", JSONArray(listOf("第1段", "第2段", "第3段"))), "2099-01-01")
            val bytes = instrumentation.context.assets.open("seek-tones.mp3").use { it.readBytes() }
            val file = temporary.resolve(article.directory).resolve("audio/圭太_位置3.4%20.mp3")
            Files.write(file, bytes)
            val url = "https://appassets.androidplatform.net/api/articles/${article.metadata.getLong("id")}/assets/audio/${android.net.Uri.encode(file.fileName.toString())}"
            val tones = Tones()
            instrumentation.runOnMainSync {
                val renderers = object : DefaultRenderersFactory(context) {
                    override fun buildAudioSink(context: Context, enableFloatOutput: Boolean, enableAudioOutputPlaybackParams: Boolean): AudioSink =
                        DefaultAudioSink.Builder(context).setAudioProcessors(arrayOf(TeeAudioProcessor(tones))).build()
                }
                media = ArticleMediaPlayer(context, temporary, renderers)
            }
            val player = media!!
            for ((position, frequency) in listOf(10.3 to 990.0, .3 to 330.0, 5.3 to 660.0, 10.3 to 990.0, .3 to 330.0)) {
                val epoch = tones.epoch
                assertTrue(player.play(url, position, 1.0))
                waitFor {
                    val state = JSONObject(player.status())
                    tones.epoch > epoch && kotlin.math.abs(tones.frequency - frequency) < 35 && state.getBoolean("playing") &&
                        state.getDouble("position") in position..position + 2
                }
                println("decodedSeek position=$position frequency=${tones.frequency} state=${player.status()}")
            }
            player.pause(); waitFor { !JSONObject(player.status()).getBoolean("playing") }
            player.rate(1.5); waitFor { JSONObject(player.status()).getDouble("rate") == 1.5 }
            assertFalse(player.play(url.replace("/api/articles/", "/api/books/"), 0.0, 1.0))
            assertFalse(player.play("https://example.test/remote.mp3", 0.0, 1.0))
            assertArrayEquals(bytes, Files.readAllBytes(file))
        } finally {
            instrumentation.runOnMainSync { media?.close() }
            scenario.close()
            temporary.toFile().deleteRecursively()
        }
    }

    private fun waitFor(condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 15000
        while (System.currentTimeMillis() < deadline) {
            if (condition()) return
            Thread.sleep(50)
        }
        fail("Decoded audio did not match the requested paragraph within 15 seconds")
    }
}
