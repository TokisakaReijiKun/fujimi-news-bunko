package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.text.Normalizer
import java.util.UUID

/** Reference WAV files remain the source of truth; no second voice registry. */
class LocalVoiceStore(private val data: Path) {
    private val folder = data.resolve("voices")

    fun files(): List<Path> {
        require(!Files.isSymbolicLink(folder)) { "声线目录不能是符号链接。" }
        if (!Files.isDirectory(folder, LinkOption.NOFOLLOW_LINKS)) return emptyList()
        return Files.list(folder).use { stream -> stream.filter { it.fileName.toString().endsWith(".wav", true) }
            .sorted().iterator().asSequence().toList() }
    }

    fun list(activeId: Long? = null): JSONArray = JSONArray(files().mapNotNull { file -> runCatching {
        val name = name(file); val duration = validate(file)
        JSONObject().put("id", id(name)).put("name", name).put("active", activeId == id(name))
            .put("duration", duration).put("read_only", false).put("saved_audio_only", true)
    }.getOrNull() })

    fun find(id: Long): JSONObject? = list().let { rows -> (0 until rows.length()).map { rows.getJSONObject(it) }.firstOrNull { it.getLong("id") == id } }

    /** Read only the validated reference belonging to this stable voice ID. */
    fun reference(voiceId: Long): Path {
        val matches = files().filter { runCatching { id(name(it)) == voiceId }.getOrDefault(false) }
        if (matches.isEmpty()) throw NoSuchElementException("参考音声が見つかりません。")
        require(matches.size == 1) { "参考音声のIDが重複しています。" }
        return matches.single().also { validate(it) }
    }

    fun saveFile(title: String, source: Path, existingId: Long? = null): JSONObject = ArticleStore(data).withSyncLock {
        val filename = existingId?.let { reference(it).fileName.toString() } ?: (name(Path.of("$title.wav")) + ".wav")
        Files.createDirectories(folder)
        val target = SyncFiles.path(folder, filename)
        require(existingId != null || !Files.exists(target, LinkOption.NOFOLLOW_LINKS)) { "同名声线已存在。" }
        val temporary = folder.resolve(".${UUID.randomUUID()}.wav")
        try {
            Files.copy(source, temporary)
            validate(temporary)
            Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        } finally { Files.deleteIfExists(temporary) }
        find(id(name(target))) ?: error("声线保存后无法读取。")
    }

    fun delete(voiceId: Long) = ArticleStore(data).withSyncLock { Files.delete(reference(voiceId)) }

    fun importFile(source: Path, verifyContent: Boolean = true): String {
        val title = name(source); validate(source)
        Files.createDirectories(folder)
        val target = SyncFiles.path(folder, "$title.wav")
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) return if (if (verifyContent) SyncFiles.hash(target) == SyncFiles.hash(source) else Files.size(target) == Files.size(source)) "unchanged" else "conflict"
        val temporary = folder.resolve(".${UUID.randomUUID()}.tmp")
        try {
            Files.copy(source, temporary)
            Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE)
        } finally { Files.deleteIfExists(temporary) }
        return "created"
    }

    companion object {
        fun name(file: Path): String {
            val filename = file.fileName.toString()
            require(filename.endsWith(".wav", true)) { "参考声线须为 WAV。" }
            val name = Normalizer.normalize(filename.dropLast(4), Normalizer.Form.NFC)
            require(name.isNotBlank() && name.codePointCount(0, name.length) <= 80 && name == name.trim() && !name.endsWith('.') &&
                name.none { it in "<>:\"/\\|?*" || it.isISOControl() }) { "声线名称无效。" }
            require(name.uppercase() !in setOf("CON", "PRN", "AUX", "NUL") && !Regex("(?:COM|LPT)\\d+", RegexOption.IGNORE_CASE).matches(name)) { "声线名称不能使用 Windows 保留名称。" }
            return name
        }
        fun key(name: String) = "voice:" + SyncFiles.hash(Normalizer.normalize(name, Normalizer.Form.NFC).toByteArray(Charsets.UTF_8))
        fun id(name: String) = key(name).substringAfter(':').take(12).toLong(16)
        fun validate(file: Path): Double {
            name(file)
            require(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) && !Files.isSymbolicLink(file)) { "声线文件无效。" }
            val fileSize = Files.size(file)
            require(fileSize in 44..20L * 1024 * 1024) { "参考声线须小于 20 MiB。" }
            return Files.newByteChannel(file).use { channel ->
                fun read(position: Long, length: Int): ByteBuffer {
                    val buffer = ByteBuffer.allocate(length).order(ByteOrder.LITTLE_ENDIAN)
                    channel.position(position)
                    while (buffer.hasRemaining()) require(channel.read(buffer) > 0) { "WAV 数据截断。" }
                    return buffer.apply { flip() }
                }
                fun marker(buffer: ByteBuffer) = String(buffer.array(), 0, 4, Charsets.US_ASCII)
                val header = read(0, 12)
                require(marker(header) == "RIFF" && String(header.array(), 8, 4, Charsets.US_ASCII) == "WAVE" &&
                    (header.getInt(4).toLong() and 0xffffffffL) + 8 == fileSize) { "参考声线不是完整 WAV。" }
                var position = 12L; var byteRate = 0L; var blockAlign = 0; var audioBytes = 0L
                while (position + 8 <= fileSize) {
                    val chunk = read(position, 8)
                    val size = chunk.getInt(4).toLong() and 0xffffffffL
                    val end = position + 8 + size
                    require(end <= fileSize) { "WAV 数据截断。" }
                    when (marker(chunk)) {
                        "fmt " -> {
                            require(size >= 16)
                            val formatChunk = read(position + 8, 16)
                            val format = formatChunk.getShort(0).toInt() and 0xffff
                            val channels = formatChunk.getShort(2).toInt() and 0xffff
                            val sampleRate = formatChunk.getInt(4)
                            byteRate = formatChunk.getInt(8).toLong() and 0xffffffffL
                            blockAlign = formatChunk.getShort(12).toInt() and 0xffff
                            val bits = formatChunk.getShort(14).toInt() and 0xffff
                            require(format in setOf(1, 3) && channels in 1..2 && sampleRate in 1..192000 && bits in setOf(8, 16, 24, 32, 64)
                                && blockAlign == channels * bits / 8 && byteRate == sampleRate.toLong() * blockAlign) { "WAV 编码不支持。" }
                        }
                        "data" -> audioBytes += size
                    }
                    position = end + size % 2
                }
                require(byteRate > 0 && blockAlign > 0 && audioBytes > 0 && audioBytes % blockAlign == 0L) { "WAV 音频无效。" }
                val duration = audioBytes.toDouble() / byteRate
                require(duration in 1.0..120.0) { "参考声线须为 1–120 秒。" }
                duration
            }
        }
    }
}
