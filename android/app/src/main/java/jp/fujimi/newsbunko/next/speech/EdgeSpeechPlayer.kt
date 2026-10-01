package jp.fujimi.newsbunko.next.speech

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.ArrayDeque
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/** Direct Microsoft Edge TTS client. It does not require a PC or Android system TTS voice. */
class EdgeSpeechPlayer(context: Context, private val event: (String, String) -> Unit) {
    private val appContext = context.applicationContext
    private val diagnostics = File(appContext.filesDir, "data/diagnostics").also { it.mkdirs() }
    private val executor = Executors.newSingleThreadExecutor()
    private val http = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(70, TimeUnit.SECONDS).build()
    private val main = Handler(Looper.getMainLooper())
    private val generation = AtomicLong()
    private val pending = ArrayDeque<String>()
    private var mediaPlayer: MediaPlayer? = null
    private var activeId: String? = null
    private var activeFile: File? = null
    private var activeRate = 1f
    private var activeVoice = ""
    private var started = false
    @Volatile private var closed = false

    fun speak(text: String, rate: Float, id: String, voice: String) {
        val token = generation.incrementAndGet()
        main.post {
            stopCurrent(emitStop = true)
            if (closed || text.isBlank() || text.length > 200_000 || voice !in setOf(EdgeVoiceCatalog.KEITA, EdgeVoiceCatalog.NANAMI)) {
                event(id, "error")
                return@post
            }
            activeId = id
            activeRate = rate
            activeVoice = voice
            started = false
            pending.addAll(splitText(text))
            downloadNext(token)
        }
    }

    fun stop() {
        generation.incrementAndGet()
        main.post { stopCurrent(emitStop = true) }
    }

    private fun downloadNext(token: Long) {
        val id = activeId ?: return
        val chunk = if (pending.isEmpty()) null else pending.removeFirst()
        if (chunk == null) return fail(id, token)
        val voice = activeVoice
        executor.execute {
            var file: File? = null
            try {
                val bytes = requestAudio(chunk, voice)
                file = File.createTempFile("edge-speech-", ".mp3", diagnostics)
                file.writeBytes(bytes)
                val saved = file
                main.post {
                    if (closed || token != generation.get() || activeId != id) {
                        saved.delete()
                        return@post
                    }
                    prepare(saved, activeRate, id, token)
                }
            } catch (_: Exception) {
                file?.delete()
                main.post { if (!closed && token == generation.get() && activeId == id) fail(id, token) }
            }
        }
    }

    private fun requestAudio(text: String, voice: String): ByteArray {
        val connectionId = UUID.randomUUID().toString().replace("-", "")
        val url = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1" +
            "?TrustedClientToken=$TRUSTED_CLIENT_TOKEN&ConnectionId=$connectionId" +
            "&Sec-MS-GEC=${secMsGec()}&Sec-MS-GEC-Version=$SEC_MS_GEC_VERSION"
        val audio = ByteArrayOutputStream()
        val finished = CountDownLatch(1)
        var failure: Throwable? = null
        val request = Request.Builder().url(url)
            .header("Pragma", "no-cache")
            .header("Cache-Control", "no-cache")
            .header("Origin", "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold")
            .header("User-Agent", USER_AGENT)
            .header("Cookie", "muid=${UUID.randomUUID().toString().replace("-", "").uppercase(Locale.US)};")
            .build()
        val socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(speechConfig())
                webSocket.send(ssml(text, voice))
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val path = textPath(text)
                if (path == "turn.end") {
                    if (audio.size() == 0) failure = IllegalStateException("Edge TTS 未返回音频。")
                    finished.countDown()
                    webSocket.close(1000, "done")
                }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                val data = bytes.toByteArray()
                if (data.size < 4) return
                val headerLength = ((data[0].toInt() and 0xff) shl 8) or (data[1].toInt() and 0xff)
                if (headerLength < 2 || headerLength + 2 > data.size) {
                    failure = IllegalStateException("Edge TTS 返回的音频头无效。")
                    finished.countDown()
                    webSocket.cancel()
                    return
                }
                val path = headerPath(data, headerLength)
                if (path == "audio" && headerLength + 2 < data.size) audio.write(data, headerLength + 2, data.size - headerLength - 2)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                failure = t
                finished.countDown()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (finished.count > 0 && audio.size() == 0) failure = IllegalStateException("Edge TTS 连接已关闭。")
                finished.countDown()
            }
        })
        if (!finished.await(70, TimeUnit.SECONDS)) {
            socket.cancel()
            throw IllegalStateException("Edge TTS 请求超时。")
        }
        failure?.let { throw it }
        return audio.toByteArray().also { if (it.isEmpty()) throw IllegalStateException("Edge TTS 未返回音频。") }
    }

    private fun speechConfig(): String {
        val timestamp = timestamp()
        return "X-Timestamp:$timestamp\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n" +
            "{\"context\":{\"synthesis\":{\"audio\":{\"metadataoptions\":{\"sentenceBoundaryEnabled\":\"false\",\"wordBoundaryEnabled\":\"false\"},\"outputFormat\":\"audio-24khz-48kbitrate-mono-mp3\"}}}}\r\n"
    }

    private fun ssml(text: String, voice: String): String {
        val cleaned = text.map { char -> if (char.code in 0..8 || char.code in 11..12 || char.code in 14..31) ' ' else char }.joinToString("")
        val escaped = cleaned.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")
        return "X-RequestId:${UUID.randomUUID().toString().replace("-", "")}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:${timestamp()}Z\r\nPath:ssml\r\n\r\n" +
            "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'><voice name='$voice'><prosody pitch='+0Hz' rate='+0%' volume='+0%'>$escaped</prosody></voice></speak>"
    }

    private fun textPath(message: String): String? {
        val split = message.indexOf("\r\n\r\n")
        if (split < 0) return null
        return headers(message.substring(0, split))["Path"]
    }

    private fun headerPath(data: ByteArray, headerLength: Int): String? {
        val header = String(data, 2, headerLength - 2, StandardCharsets.UTF_8)
        return headers(header)["Path"]
    }

    private fun headers(value: String): Map<String, String> = value.split("\r\n").mapNotNull {
        val split = it.indexOf(':')
        if (split <= 0) null else it.substring(0, split) to it.substring(split + 1)
    }.toMap()

    private fun secMsGec(): String {
        val unixSeconds = System.currentTimeMillis() / 1000L
        val windowsSeconds = (unixSeconds + WINDOWS_EPOCH_SECONDS) / 300L * 300L
        val ticks = windowsSeconds * 10_000_000L
        return sha256("$ticks$TRUSTED_CLIENT_TOKEN").uppercase(Locale.US)
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(StandardCharsets.US_ASCII)).joinToString("") { "%02x".format(it) }

    private fun timestamp(): String = SimpleDateFormat("EEE MMM dd yyyy HH:mm:ss 'GMT+0000 (Coordinated Universal Time)'", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }.format(Date())

    private fun prepare(file: File, rate: Float, id: String, token: Long) {
        releasePlayer(deleteFile = true)
        val player = MediaPlayer()
        mediaPlayer = player
        activeFile = file
        player.setAudioAttributes(AudioAttributes.Builder().setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).setUsage(AudioAttributes.USAGE_MEDIA).build())
        player.setOnPreparedListener {
            if (player !== mediaPlayer || closed || token != generation.get()) return@setOnPreparedListener
            if (android.os.Build.VERSION.SDK_INT >= 23) player.playbackParams = player.playbackParams.setSpeed(rate.coerceIn(0.5f, 2f))
            player.start()
            if (!started) {
                started = true
                event(id, "start")
            }
        }
        player.setOnCompletionListener { completeChunk(id, token) }
        player.setOnErrorListener { _, _, _ -> fail(id, token); true }
        try {
            player.setDataSource(file.absolutePath)
            player.prepareAsync()
        } catch (_: Exception) {
            fail(id, token)
        }
    }

    private fun completeChunk(id: String, token: Long) {
        if (activeId != id || token != generation.get()) return
        releasePlayer(deleteFile = true)
        if (pending.isNotEmpty()) downloadNext(token)
        else {
            activeId = null
            event(id, "done")
        }
    }

    private fun fail(id: String, token: Long) {
        if (activeId != id || token != generation.get()) return
        releasePlayer(deleteFile = true)
        pending.clear()
        activeId = null
        event(id, "error")
    }

    private fun releasePlayer(deleteFile: Boolean) {
        val old = mediaPlayer
        mediaPlayer = null
        try { old?.stop() } catch (_: Exception) { }
        old?.release()
        if (deleteFile) activeFile?.delete()
        activeFile = null
    }

    private fun stopCurrent(emitStop: Boolean) {
        val id = activeId
        pending.clear()
        activeId = null
        releasePlayer(deleteFile = true)
        if (emitStop && id != null) event(id, "stop")
    }

    private fun splitText(text: String, limit: Int = 3500): List<String> {
        val chunks = mutableListOf<String>()
        val current = StringBuilder()
        var bytes = 0
        text.forEach { char ->
            val size = char.toString().toByteArray(StandardCharsets.UTF_8).size
            if (current.isNotEmpty() && bytes + size > limit) {
                chunks += current.toString().trim()
                current.clear()
                bytes = 0
            }
            current.append(char)
            bytes += size
        }
        if (current.isNotEmpty()) chunks += current.toString().trim()
        return chunks.filter { it.isNotEmpty() }
    }

    fun close() {
        closed = true
        generation.incrementAndGet()
        main.post { stopCurrent(emitStop = false) }
        http.dispatcher.executorService.shutdownNow()
        http.connectionPool.evictAll()
        executor.shutdownNow()
    }

    private companion object {
        const val TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
        const val WINDOWS_EPOCH_SECONDS = 11644473600L
        const val SEC_MS_GEC_VERSION = "1-143.0.3650.75"
        const val USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
    }
}
