package jp.fujimi.newsbunko.next.store

import java.nio.file.FileAlreadyExistsException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.security.MessageDigest
import java.util.UUID

enum class InstallResult { WRITTEN, ALREADY_PRESENT }

class PathConflictException(val relativePath: String) : Exception("同步路径已有不同内容：$relativePath")
class ChecksumMismatchException(val relativePath: String) : Exception("同步文件校验失败：$relativePath")

/** Installs PC-format content without altering its relative path or extension. */
class PreservedPathStore(private val dataRoot: Path) {
    private val roots = setOf("articles", "bookmarks", "books", "voices")

    @Synchronized
    fun install(relativePath: String, bytes: ByteArray): InstallResult = install(
        relativePath, ByteArrayInputStream(bytes), sha256(bytes)
    )

    @Synchronized
    fun install(relativePath: String, input: InputStream, expectedSha256: String): InstallResult {
        require(Regex("[a-f0-9]{64}").matches(expectedSha256)) { "无效的文件校验值" }
        val destination = resolveContentPath(relativePath)
        Files.createDirectories(dataRoot)
        val temporaryRoot = dataRoot.resolve("diagnostics/transactions")
        Files.createDirectories(temporaryRoot)
        val staged = temporaryRoot.resolve("sync-${UUID.randomUUID()}.tmp")
        try {
            val hash = MessageDigest.getInstance("SHA-256")
            Files.newOutputStream(staged).use { output ->
                input.use { source ->
                    val buffer = ByteArray(64 * 1024)
                    var length = source.read(buffer)
                    while (length >= 0) {
                        if (length > 0) {
                            output.write(buffer, 0, length)
                            hash.update(buffer, 0, length)
                        }
                        length = source.read(buffer)
                    }
                }
            }
            if (hex(hash.digest()) != expectedSha256) throw ChecksumMismatchException(relativePath)
            var parent = dataRoot.toAbsolutePath().normalize()
            for (segment in parent.relativize(destination.parent)) {
                parent = parent.resolve(segment)
                if (Files.isSymbolicLink(parent)) throw IllegalArgumentException("同步路径包含符号链接")
                Files.createDirectories(parent)
            }
            if (Files.isSymbolicLink(destination)) throw IllegalArgumentException("同步目标是符号链接")
            if (Files.exists(destination, LinkOption.NOFOLLOW_LINKS)) {
                if (Files.isRegularFile(destination) && sha256(Files.newInputStream(destination)) == expectedSha256) {
                    return InstallResult.ALREADY_PRESENT
                }
                throw PathConflictException(relativePath)
            }
            try {
                Files.move(staged, destination)
            } catch (_: FileAlreadyExistsException) {
                throw PathConflictException(relativePath)
            }
            return InstallResult.WRITTEN
        } finally {
            Files.deleteIfExists(staged)
        }
    }

    private fun sha256(bytes: ByteArray): String = hex(MessageDigest.getInstance("SHA-256").digest(bytes))

    private fun sha256(input: InputStream): String = input.use { source ->
        val hash = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(64 * 1024)
        var length = source.read(buffer)
        while (length >= 0) {
            if (length > 0) hash.update(buffer, 0, length)
            length = source.read(buffer)
        }
        hex(hash.digest())
    }

    private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

    fun resolveContentPath(relativePath: String): Path {
        require(relativePath.isNotEmpty() && !relativePath.startsWith('/') && '\\' !in relativePath) { "同步路径必须是相对 POSIX 路径" }
        val parts = relativePath.split('/')
        require(parts.size >= 2 && parts[0] in roots && parts.all { part ->
            part.isNotEmpty() && part != "." && part != ".." && ':' !in part && '\u0000' !in part
        }) { "同步路径不属于文库内容目录" }
        val root = dataRoot.toAbsolutePath().normalize()
        val destination = root.resolve(relativePath).normalize()
        require(destination.startsWith(root)) { "同步路径越过文库目录" }
        return destination
    }
}
