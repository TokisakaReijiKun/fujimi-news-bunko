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
            .put("duration", duration).put("read_only", true).put("saved_audio_only", true)
    }.getOrNull() })

    fun find(id: Long): JSONObject? = list().let { rows -> (0 until rows.length()).map { rows.getJSONObject(it) }.firstOrNull { it.getLong("id") == id } }

    fun importFile(source: Path): String {
        val title = name(source); validate(source)
        Files.createDirectories(folder)
        val target = SyncFiles.path(folder, "$title.wav")
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) return if (SyncFiles.hash(target) == SyncFiles.hash(source)) "unchanged" else "conflict"
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
            require(Files.size(file) in 44..20L * 1024 * 1024) { "参考声线须小于 20 MiB。" }
            val bytes = Files.readAllBytes(file)
            val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            fun marker(position: Int) = String(bytes, position, 4, Charsets.US_ASCII)
            require(marker(0) == "RIFF" && marker(8) == "WAVE" && buffer.getInt(4).toLong() + 8 == bytes.size.toLong()) { "参考声线不是完整 WAV。" }
            var position = 12; var byteRate = 0L; var blockAlign = 0; var audioBytes = 0L
            while (position + 8 <= bytes.size) {
                val size = buffer.getInt(position + 4).toLong() and 0xffffffffL
                val end = position.toLong() + 8 + size
                require(end <= bytes.size) { "WAV 数据截断。" }
                when (marker(position)) {
                    "fmt " -> {
                        require(size >= 16)
                        val format = buffer.getShort(position + 8).toInt() and 0xffff
                        val channels = buffer.getShort(position + 10).toInt() and 0xffff
                        val sampleRate = buffer.getInt(position + 12)
                        byteRate = buffer.getInt(position + 16).toLong() and 0xffffffffL
                        blockAlign = buffer.getShort(position + 20).toInt() and 0xffff
                        val bits = buffer.getShort(position + 22).toInt() and 0xffff
                        require(format in setOf(1, 3) && channels in 1..2 && sampleRate in 1..192000 && bits in setOf(8, 16, 24, 32, 64)
                            && blockAlign == channels * bits / 8 && byteRate == sampleRate.toLong() * blockAlign) { "WAV 编码不支持。" }
                    }
                    "data" -> audioBytes += size
                }
                position = (end + size % 2).toInt()
            }
            require(byteRate > 0 && blockAlign > 0 && audioBytes > 0 && audioBytes % blockAlign == 0L) { "WAV 音频无效。" }
            val duration = audioBytes.toDouble() / byteRate
            require(duration in 1.0..120.0) { "参考声线须为 1–120 秒。" }
            return duration
        }
    }
}
