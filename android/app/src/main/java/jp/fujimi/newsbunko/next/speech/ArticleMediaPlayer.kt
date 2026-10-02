package jp.fujimi.newsbunko.next.speech

import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.RenderersFactory
import androidx.media3.exoplayer.SeekParameters
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.extractor.DefaultExtractorsFactory
import androidx.media3.extractor.mp3.Mp3Extractor
import jp.fujimi.newsbunko.next.store.ArticleAudioAccess
import org.json.JSONObject
import java.nio.file.Path
import kotlin.math.roundToLong

/** Implements the saved-audio bridge already used by the original APK's player. */
@androidx.annotation.OptIn(markerClass = [UnstableApi::class])
class ArticleMediaPlayer(context: Context, private val data: Path,
                         renderers: RenderersFactory = DefaultRenderersFactory(context)) {
    private val main = Handler(Looper.getMainLooper())
    private val player = ExoPlayer.Builder(context, renderers)
        .setMediaSourceFactory(DefaultMediaSourceFactory(DefaultDataSource.Factory(context),
            DefaultExtractorsFactory().setMp3ExtractorFlags(Mp3Extractor.FLAG_ENABLE_INDEX_SEEKING)))
        .build().apply {
            setSeekParameters(SeekParameters.EXACT)
            setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_SPEECH).build(), true)
        }
    private var source: Path? = null
    private var error = ""
    @Volatile private var closed = false
    @Volatile private var snapshot = emptyStatus()
    private val poll = object : Runnable {
        override fun run() {
            if (closed) return
            publish()
            main.postDelayed(this, 100)
        }
    }

    init {
        player.addListener(object : Player.Listener {
            override fun onEvents(player: Player, events: Player.Events) = publish()
            override fun onPlayerError(failure: PlaybackException) {
                error = "本地音频无法播放（${failure.errorCodeName}）。"
                publish()
            }
        })
        main.post(poll)
    }

    fun play(url: String, position: Double, rate: Double): Boolean {
        if (closed || !position.isFinite() || position < 0 || !rate.isFinite() || rate !in 0.5..2.0) return false
        val path = try {
            val uri = Uri.parse(url)
            require(uri.scheme == "https" && uri.host == "appassets.androidplatform.net" && uri.port == -1)
            val match = Regex("/api/articles/(\\d+)/assets/audio/(.+)").matchEntire(uri.path.orEmpty()) ?: return false
            ArticleAudioAccess(data).resolve(match.groupValues[1].toLong(), match.groupValues[2])
        } catch (_: Exception) { return false }
        main.post {
            if (closed) return@post
            error = ""
            if (path != source || player.playbackState == Player.STATE_IDLE || player.playerError != null) {
                source = path
                player.setMediaItem(MediaItem.fromUri(Uri.fromFile(path.toFile())), (position * 1000).roundToLong())
                player.prepare()
            } else player.seekTo((position * 1000).roundToLong())
            player.setPlaybackSpeed(rate.toFloat())
            player.play()
            publish()
        }
        return true
    }

    fun status(): String = snapshot
    fun pause() = main.post { if (!closed) { player.pause(); publish() } }
    fun seek(position: Double) {
        if (position.isFinite() && position >= 0) main.post { if (!closed) { player.seekTo((position * 1000).roundToLong()); publish() } }
    }
    fun rate(rate: Double) {
        if (rate.isFinite() && rate in 0.5..2.0) main.post { if (!closed) { player.setPlaybackSpeed(rate.toFloat()); publish() } }
    }
    fun stop() = main.post {
        if (!closed) { player.stop(); player.clearMediaItems(); source = null; error = ""; snapshot = emptyStatus() }
    }
    private fun publish() {
        snapshot = JSONObject().put("playing", player.isPlaying).put("position", player.currentPosition / 1000.0)
            .put("duration", if (player.duration == C.TIME_UNSET) 0.0 else player.duration / 1000.0)
            .put("ended", player.playbackState == Player.STATE_ENDED).put("rate", player.playbackParameters.speed)
            .put("error", error).toString()
    }
    fun close() {
        closed = true
        main.removeCallbacks(poll)
        main.post { player.release() }
    }
    private fun emptyStatus() = "{\"playing\":false,\"position\":0,\"duration\":0,\"ended\":false,\"rate\":1,\"error\":\"\"}"
}
