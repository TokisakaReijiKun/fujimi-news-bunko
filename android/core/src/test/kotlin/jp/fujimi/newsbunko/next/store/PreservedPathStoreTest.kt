package jp.fujimi.newsbunko.next.store

import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.io.ByteArrayInputStream

class PreservedPathStoreTest {
    @TempDir lateinit var temporary: Path

    @Test fun copiesNestedPcPathsWithoutRenaming() {
        val store = PreservedPathStore(temporary.resolve("data"))
        val epub = byteArrayOf(0x50, 0x4b, 0x03, 0x04)
        val media = byteArrayOf(1, 2, 3)

        assertEquals(InstallResult.WRITTEN, store.install("books/星の旅/原本.epub", epub))
        assertEquals(InstallResult.WRITTEN, store.install("articles/2026-09-29/日本の景色/media/image-001.jpg", media))
        assertArrayEquals(epub, Files.readAllBytes(temporary.resolve("data/books/星の旅/原本.epub")))
        assertArrayEquals(media, Files.readAllBytes(temporary.resolve("data/articles/2026-09-29/日本の景色/media/image-001.jpg")))
        assertEquals(InstallResult.ALREADY_PRESENT, store.install("books/星の旅/原本.epub", epub))
        assertEquals(listOf("原本.epub"), Files.list(temporary.resolve("data/books/星の旅")).use { stream ->
            stream.map { it.fileName.toString() }.toList()
        })
    }

    @Test fun rejectsConflictingBytesWithoutChangingEitherNameOrContent() {
        val store = PreservedPathStore(temporary.resolve("data"))
        val relative = "books/同名/原本.epub"
        store.install(relative, byteArrayOf(1, 2))

        assertThrows(PathConflictException::class.java) { store.install(relative, byteArrayOf(3, 4)) }
        assertArrayEquals(byteArrayOf(1, 2), Files.readAllBytes(temporary.resolve("data/$relative")))
        assertEquals(1L, Files.list(temporary.resolve("data/books/同名")).use { it.count() })
    }

    @Test fun refusesTraversalAndUnlistedRootDirectories() {
        val store = PreservedPathStore(temporary.resolve("data"))

        listOf("../outside", "books/../outside", "/books/outside", "books\\outside", "cache/hidden").forEach { path ->
            assertThrows(IllegalArgumentException::class.java) { store.install(path, byteArrayOf(1)) }
        }
        assertEquals(false, Files.exists(temporary.resolve("outside")))
    }

    @Test fun streamsLargeFileAndRejectsIncorrectChecksumBeforeCommit() {
        val store = PreservedPathStore(temporary.resolve("data"))
        val relative = "books/海辺/第１巻.epub"
        val payload = ByteArray(1_000_000) { index -> (index % 251).toByte() }

        assertThrows(ChecksumMismatchException::class.java) {
            store.install(relative, ByteArrayInputStream(payload), "0".repeat(64))
        }
        assertEquals(false, Files.exists(temporary.resolve("data/$relative")))
        assertEquals(InstallResult.WRITTEN, store.install(relative, ByteArrayInputStream(payload),
            "2c030d49ec131bfbbb446ad21e7a2f12cdb4f2f4f3fda3ac709dd2e68a4646c7"))
        assertArrayEquals(payload, Files.readAllBytes(temporary.resolve("data/$relative")))
    }
}
