package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import java.util.zip.ZipFile
import jp.fujimi.newsbunko.next.daily.StoredMedia

class LibrarySyncStoreTest {
    @TempDir lateinit var temporary: Path

    @Test fun `missing nested book images are filled in the existing book by a file delta`() {
        val source = temporary.resolve("pc")
        val target = temporary.resolve("phone")
        val sourceStore = LibrarySyncStore(source)
        val targetStore = LibrarySyncStore(target)
        sourceStore.importBundle(Path.of("../../tests/fixtures/sync-v2/book.zip"))
        val sourceFolder = source.resolve("books/同期の本")
        val meta = SyncFiles.json(sourceFolder.resolve("book.json"))
        val imagePaths = (0 until 29).map { "resources/OEBPS/Images/embed${it.toString().padStart(4, '0')}_HD.jpg" }
        imagePaths.forEachIndexed { index, name ->
            val bytes = ByteArray(100 + index) { index.toByte() }
            val file = sourceFolder.resolve(name)
            Files.createDirectories(file.parent); Files.write(file, bytes)
            meta.getJSONObject("resources").put(name.removePrefix("resources/"), JSONObject().put("bytes", bytes.size).put("sha256", SyncFiles.hash(bytes)))
        }
        meta.getJSONObject("book").put("cover_path", imagePaths.last().removePrefix("resources/"))
        SyncFiles.writeJson(sourceFolder.resolve("book.json"), meta)
        val full = temporary.resolve("book-full.zip")
        val remote = sourceStore.manifest().getJSONArray("items").getJSONObject(0)
        sourceStore.exportBundle(remote.getString("key"), full)
        targetStore.importBundle(full)
        val targetFolder = target.resolve("books/同期の本")
        val state = SyncFiles.json(targetFolder.resolve("state.json")).put("progress", JSONObject().put("chapter", 1).put("offset", 20))
        SyncFiles.writeJson(targetFolder.resolve("state.json"), state)
        val originalMeta = Files.readAllBytes(targetFolder.resolve("book.json"))
        val originalState = Files.readAllBytes(targetFolder.resolve("state.json"))
        imagePaths.forEach { Files.delete(targetFolder.resolve(it)) }

        val localManifest = targetStore.manifest()
        assertEquals(1, localManifest.getJSONArray("items").length(), "Missing images must not remove the book's identity")
        assertEquals(0, localManifest.getJSONArray("errors").length())
        val local = localManifest.getJSONArray("items").getJSONObject(0)
        assertTrue(LibrarySyncStore.needsTransfer(remote, local))
        imagePaths.forEach { assertFalse(local.getJSONObject("files").has(it)) }
        assertTrue(local.getJSONObject("files").has("resources/cover.png"))
        assertThrows(IllegalArgumentException::class.java) { SyncFiles.validate("book", targetFolder, verifyContent = false) }
        assertThrows(IllegalArgumentException::class.java) { targetStore.exportBundle(remote.getString("key"), temporary.resolve("incomplete.zip")) }
        val delta = temporary.resolve("book-images.zip")
        sourceStore.exportBundle(remote.getString("key"), delta, local.getJSONObject("files"))
        ZipFile(delta.toFile()).use { zip ->
            assertEquals((imagePaths.map { "files/$it" } + listOf("bundle.json", "files/book.json", "files/state.json")).toSet(), zip.entries().asSequence().map { it.name }.toSet())
        }
        assertEquals("updated", targetStore.importBundle(delta).getString("status"))
        assertArrayEquals(originalMeta, Files.readAllBytes(targetFolder.resolve("book.json")))
        assertArrayEquals(originalState, Files.readAllBytes(targetFolder.resolve("state.json")))
        imagePaths.forEach { assertArrayEquals(Files.readAllBytes(sourceFolder.resolve(it)), Files.readAllBytes(targetFolder.resolve(it))) }
        Files.list(target.resolve("books")).use { assertEquals(1L, it.count()) }
        val repaired = targetStore.manifest().getJSONArray("items").getJSONObject(0)
        assertFalse(LibrarySyncStore.needsTransfer(remote, repaired))
        val coverUrl = JSONObject(LocalSyncedLibraryApi(target).request("GET", "/api/books")!!.body).getJSONArray("books").getJSONObject(0).getString("cover_url")
        assertTrue(coverUrl.endsWith("/assets/OEBPS/Images/embed0028_HD.jpg"))
        assertArrayEquals(Files.readAllBytes(sourceFolder.resolve(imagePaths.last())), Files.readAllBytes(LocalSyncedLibraryApi(target).asset(1, imagePaths.last().removePrefix("resources/"))))
    }

    private fun article(root: Path, title: String, text: String) = ArticleStore(root).create(JSONObject()
        .put("title", title).put("url", "https://example.com/$title").put("paragraphs", JSONArray(listOf(text))), "2026-10-17")

    @Test fun `manifest compares paths and lengths without checking file digests`() {
        val root = temporary.resolve("pc")
        val saved = article(root, "長さ比較", "新聞本文。")
        val folder = root.resolve(saved.directory)
        // The sync contract accepts an equal-length file even when its stored digest differs.
        Files.write(folder.resolve("original.txt"), "同長本文。".toByteArray(Charsets.UTF_8))
        val manifest = LibrarySyncStore(root).manifest()
        assertEquals(0, manifest.getJSONArray("errors").length())
        assertEquals("path-size-v1", manifest.getString("file_comparison"))
        val item = manifest.getJSONArray("items").getJSONObject(0)
        assertFalse(item.has("fingerprint"))
        assertFalse(item.getBoolean("bookmarked"))
        assertEquals(Files.size(folder.resolve("original.txt")), item.getJSONObject("files").getLong("original.txt"))
        assertThrows(ArticleFormatException::class.java) { ArticleReader(root).load(saved.directory) }
    }

    @Test fun `sync plan ignores local metadata and progress but detects missing paths and bookmarks`() {
        fun item() = JSONObject().put("kind", "article").put("bookmarked", false).put("files", JSONObject()
            .put("article.json", 20).put("state.json", 10).put("original.txt", 15).put("audio/七海.mp3", 64))
        val source = item()
        val local = item()
        local.getJSONObject("files").put("article.json", 1000).put("state.json", 999)
        assertTrue(LibrarySyncStore.needsTransfer(source, null))
        assertFalse(LibrarySyncStore.needsTransfer(source, local))
        local.getJSONObject("files").remove("audio/七海.mp3")
        assertTrue(LibrarySyncStore.needsTransfer(source, local))
        local.getJSONObject("files").put("audio/七海.mp3", 63)
        assertTrue(LibrarySyncStore.needsTransfer(source, local))
        local.getJSONObject("files").put("audio/七海.mp3", 64)
        source.put("bookmarked", true)
        assertTrue(LibrarySyncStore.needsTransfer(source, local))
        local.put("bookmarked", true)
        assertFalse(LibrarySyncStore.needsTransfer(source, local))
    }

    @Test fun `chapter features ignore serialization size and transfer only missing enhancements`() {
        val name = "chapters/0001.json"
        fun book(size: Int, flags: List<String>) = JSONObject().put("kind", "book")
            .put("files", JSONObject().put("book.json", 200).put(name, size))
            .put("chapter_features", JSONObject().put(name, JSONArray(flags)))
        val source = book(500, listOf("zh:0", "ruby:0"))
        val target = book(300, listOf("zh:0", "ruby:0", "audio:七海.mp3"))
        assertFalse(LibrarySyncStore.needsTransfer(source, target))
        source.getJSONObject("chapter_features").getJSONArray(name).put("zh:1")
        assertTrue(LibrarySyncStore.needsTransfer(source, target))
        target.getJSONObject("chapter_features").getJSONArray(name).put("zh:1")
        assertFalse(LibrarySyncStore.needsTransfer(source, target))
        target.remove("chapter_features")
        assertTrue(LibrarySyncStore.needsTransfer(source, target))
        target.getJSONObject("files").put(name, 500)
        assertFalse(LibrarySyncStore.needsTransfer(source, target))
        target.getJSONObject("files").remove(name)
        assertTrue(LibrarySyncStore.needsTransfer(source, target))
    }

    @Test fun `book manifest exposes per block enhancements and chapter audio paths`() {
        val root = temporary.resolve("phone")
        val store = LibrarySyncStore(root)
        store.importBundle(Path.of("../../tests/fixtures/sync-v2/book.zip"))
        val path = root.resolve("books/同期の本/chapters/0001.json")
        val chapter = SyncFiles.json(path)
        chapter.getJSONArray("blocks").getJSONObject(0).put("furigana_html", "<ruby>本<rt>ほん</rt></ruby>")
        chapter.put("audio", JSONObject().put("path", "七海.mp3"))
        chapter.put("audio_versions", JSONArray().put(JSONObject().put("path", "圭太.mp3")))
        SyncFiles.writeJson(path, chapter)
        val item = store.manifest().getJSONArray("items").getJSONObject(0)
        val flags = item.getJSONObject("chapter_features").getJSONArray("chapters/0001.json")
        assertEquals(setOf("zh:0", "ruby:0", "audio:七海.mp3", "audio:圭太.mp3"), (0 until flags.length()).map(flags::getString).toSet())
    }

    @Test fun `same size chapter gains missing translation and additional audio versions once`() {
        val source = temporary.resolve("pc")
        val target = temporary.resolve("phone")
        val sourceStore = LibrarySyncStore(source)
        val targetStore = LibrarySyncStore(target)
        val fixture = Path.of("../../tests/fixtures/sync-v2/book.zip")
        sourceStore.importBundle(fixture); targetStore.importBundle(fixture)
        val name = "chapters/0001.json"
        fun prepare(root: Path, voice: String, translated: Boolean): ByteArray {
            val folder = root.resolve("books/同期の本")
            val chapter = SyncFiles.json(folder.resolve(name))
            if (!translated) chapter.getJSONArray("blocks").getJSONObject(0).put("text_zh", "")
            chapter.put("audio", JSONObject().put("path", "$voice.mp3"))
            chapter.put("audio_versions", JSONArray().put(JSONObject().put("path", "$voice.mp3")))
            Files.createDirectories(folder.resolve("audio"))
            Files.write(folder.resolve("audio/$voice.mp3"), byteArrayOf(1, 2, 3))
            val meta = SyncFiles.json(folder.resolve("book.json"))
            meta.put("audio", JSONObject().put("$voice.mp3", JSONObject().put("sha256", SyncFiles.hash(byteArrayOf(1, 2, 3)))))
            SyncFiles.writeJson(folder.resolve("book.json"), meta)
            return chapter.toString().toByteArray(Charsets.UTF_8)
        }
        val remoteBytes = prepare(source, "七海", true)
        val localBytes = prepare(target, "圭太", false)
        val length = maxOf(remoteBytes.size, localBytes.size)
        fun padded(bytes: ByteArray) = bytes + ByteArray(length - bytes.size) { 32 }
        Files.write(source.resolve("books/同期の本/$name"), padded(remoteBytes))
        Files.write(target.resolve("books/同期の本/$name"), padded(localBytes))
        val remoteItem = sourceStore.manifest().getJSONArray("items").getJSONObject(0)
        val localItem = targetStore.manifest().getJSONArray("items").getJSONObject(0)
        assertTrue(LibrarySyncStore.needsTransfer(remoteItem, localItem))
        val known = localItem.getJSONObject("files").also { it.remove(name) }
        val zip = temporary.resolve("chapter-delta.zip")
        sourceStore.exportBundle(remoteItem.getString("key"), zip, known)
        assertEquals("updated", targetStore.importBundle(zip).getString("status"))
        val chapter = SyncFiles.json(target.resolve("books/同期の本/$name"))
        assertEquals("书的正文。", chapter.getJSONArray("blocks").getJSONObject(0).getString("text_zh"))
        assertEquals("圭太.mp3", chapter.getJSONObject("audio").getString("path"))
        val versions = chapter.getJSONArray("audio_versions")
        assertEquals(setOf("圭太.mp3", "七海.mp3"), (0 until versions.length()).map { versions.getJSONObject(it).getString("path") }.toSet())
        assertFalse(LibrarySyncStore.needsTransfer(remoteItem, targetStore.manifest().getJSONArray("items").getJSONObject(0)))
    }

    @Test fun `new audio transfers only its bytes and preserves local metadata and progress`() {
        val source = temporary.resolve("pc")
        val destination = temporary.resolve("phone")
        val remote = article(source, "差分記事", "新聞本文。")
        article(destination, "先在記事", "本機本文。")
        val sourceStore = LibrarySyncStore(source)
        val targetStore = LibrarySyncStore(destination)
        val key = "article:${remote.metadata.getString("storage_key") }"
        val full = temporary.resolve("full.zip")
        sourceStore.exportBundle(key, full)
        targetStore.importBundle(full)
        val local = ArticleCatalog(destination).onDay("2026-10-17").single { it.metadata.getString("title") == "差分記事" }
        val localManifest = SyncFiles.json(destination.resolve(local.directory).resolve("article.json"))
        localManifest.getJSONObject("article").put("progress", JSONObject().put("paragraph", 2))
        SyncFiles.writeJson(destination.resolve(local.directory).resolve("article.json"), localManifest)
        val knownItem = targetStore.manifest().getJSONArray("items").let { rows ->
            (0 until rows.length()).map { rows.getJSONObject(it) }.single { it.getString("key") == key }
        }
        val audio = ByteArray(64) { it.toByte() }
        Files.write(source.resolve(remote.directory).resolve("audio/七海.mp3"), audio)
        val delta = temporary.resolve("delta.zip")
        sourceStore.exportBundle(key, delta, knownItem.getJSONObject("files"))
        ZipFile(delta.toFile()).use { zip ->
            val description = JSONObject(zip.getInputStream(zip.getEntry("bundle.json")).reader(Charsets.UTF_8).use { it.readText() })
            assertEquals(2, description.getInt("version"))
            assertEquals(setOf("bundle.json", "files/article.json", "files/audio/七海.mp3"), zip.entries().asSequence().map { it.name }.toSet())
            assertEquals(setOf("article.json", "audio/七海.mp3"), description.getJSONArray("included").let { (0 until it.length()).map(it::getString).toSet() })
            assertTrue((0 until description.getJSONArray("files").length()).all { !description.getJSONArray("files").getJSONObject(it).has("sha256") })
        }
        assertEquals("updated", targetStore.importBundle(delta).getString("status"))
        val result = ArticleCatalog(destination).find(local.metadata.getLong("id"))
        assertEquals(2, result.metadata.getJSONObject("progress").getInt("paragraph"))
        assertArrayEquals(audio, Files.readAllBytes(destination.resolve(result.directory).resolve("audio/七海.mp3")))
        val target = targetStore.manifest().getJSONArray("items").let { rows -> (0 until rows.length()).map { rows.getJSONObject(it) }.single { it.getString("key") == key } }
        assertFalse(LibrarySyncStore.needsTransfer(sourceStore.manifest().getJSONArray("items").getJSONObject(0), target))
        assertThrows(Exception::class.java) { LibrarySyncStore(temporary.resolve("empty")).importBundle(delta) }
        Files.write(destination.resolve(result.directory).resolve("original.txt"), byteArrayOf(1))
        assertThrows(Exception::class.java) { targetStore.importBundle(delta) }
    }

    @Test fun `equal length attachment contents are accepted without hashes and retained locally`() {
        val source = temporary.resolve("pc")
        val destination = temporary.resolve("phone")
        val remote = ArticleStore(source).create(JSONObject().put("title", "画像記事").put("url", "https://example.com/image")
            .put("paragraphs", JSONArray(listOf("本文。"))).put("image_paths", JSONArray(listOf("media/写真.jpg"))), "2026-10-17",
            listOf(StoredMedia("media/写真.jpg", byteArrayOf(1, 2, 3), "image")))
        val key = "article:${remote.metadata.getString("storage_key") }"
        val zip = temporary.resolve("image.zip")
        LibrarySyncStore(source).exportBundle(key, zip)
        LibrarySyncStore(destination).importBundle(zip)
        Files.write(source.resolve(remote.directory).resolve("media/写真.jpg"), byteArrayOf(7, 8, 9))
        LibrarySyncStore(source).exportBundle(key, zip)
        assertEquals("unchanged", LibrarySyncStore(destination).importBundle(zip).getString("status"))
        val local = ArticleCatalog(destination).onDay("2026-10-17").single()
        assertArrayEquals(byteArrayOf(1, 2, 3), Files.readAllBytes(destination.resolve(local.directory).resolve("media/写真.jpg")))
    }

    @Test fun `article transfer installs actual files and remaps a colliding local ID`() {
        val source = temporary.resolve("pc")
        val destination = temporary.resolve("phone")
        val remote = article(source, "PC記事", "新聞本文。")
        val local = article(destination, "手機記事", "本機本文。")
        val zip = temporary.resolve("article.zip")
        val key = "article:${remote.metadata.getString("storage_key")}"
        LibrarySyncStore(source).exportBundle(key, zip)
        assertEquals("created", LibrarySyncStore(destination).importBundle(zip).getString("status"))
        val rows = ArticleCatalog(destination).onDay("2026-10-17")
        assertEquals(2, rows.size)
        val received = rows.single { it.metadata.getString("title") == "PC記事" }
        assertEquals(listOf("新聞本文。"), received.paragraphs)
        assertNotEquals(local.metadata.getLong("id"), received.metadata.getLong("id"))
        assertEquals("unchanged", LibrarySyncStore(destination).importBundle(zip).getString("status"))
    }

    @Test fun `same identity with changed original is a conflict and preserves local files`() {
        val source = temporary.resolve("pc")
        val destination = temporary.resolve("phone")
        val remote = article(source, "同名記事", "電腦正文。")
        article(destination, "同名記事", "手機修改正文。")
        val zip = temporary.resolve("conflict.zip")
        LibrarySyncStore(source).exportBundle("article:${remote.metadata.getString("storage_key")}", zip)
        assertEquals("conflict", LibrarySyncStore(destination).importBundle(zip).getString("status"))
        assertEquals(listOf("手機修改正文。"), ArticleCatalog(destination).onDay("2026-10-17").single().paragraphs)
    }

    @Test fun `bundle traversal and unlisted files cannot escape staging`() {
        val zip = temporary.resolve("unsafe.zip")
        ZipOutputStream(Files.newOutputStream(zip)).use { output ->
            output.putNextEntry(ZipEntry("../escaped")); output.write(byteArrayOf(1)); output.closeEntry()
        }
        assertThrows(Exception::class.java) { LibrarySyncStore(temporary.resolve("phone")).importBundle(zip) }
        assertFalse(Files.exists(temporary.resolve("escaped")))
    }

    @Test fun `PC Store fixtures round trip actual article book and example contents`() {
        val root = temporary.resolve("phone")
        val store = LibrarySyncStore(root)
        val fixtures = Path.of("../../tests/fixtures/sync-v2")
        for (kind in listOf("article", "book", "example")) {
            assertEquals("created", store.importBundle(fixtures.resolve("$kind.zip")).getString("status"), kind)
            assertEquals("unchanged", store.importBundle(fixtures.resolve("$kind.zip")).getString("status"), kind)
        }
        val article = ArticleCatalog(root).onDay("2026-10-17").single()
        assertEquals(listOf("本文😀。"), article.paragraphs)
        assertTrue(Files.exists(root.resolve("bookmarks/端末同期のニュース/article.json")))
        assertEquals("book", store.manifest().getJSONArray("items").getJSONObject(1).getString("kind"))
        val state = SyncFiles.json(root.resolve("books/同期の本/state.json"))
        state.put("progress", JSONObject().put("chapter", 1)).put("last_read_at", "2026-10-18")
        SyncFiles.writeJson(root.resolve("books/同期の本/state.json"), state)
        assertEquals("unchanged", store.importBundle(fixtures.resolve("book.zip")).getString("status"))
        assertEquals(1, SyncFiles.json(root.resolve("books/同期の本/state.json")).getJSONObject("progress").getInt("chapter"))
        val items = store.manifest().getJSONArray("items")
        val roundtrip = LibrarySyncStore(temporary.resolve("roundtrip"))
        for (i in 0 until items.length()) {
            val zip = temporary.resolve("roundtrip-$i.zip")
            store.exportBundle(items.getJSONObject(i).getString("key"), zip)
            assertEquals("created", roundtrip.importBundle(zip).getString("status"))
        }
        assertEquals(3, roundtrip.manifest().getJSONArray("items").length())
    }

    @Test fun `existing article gains missing translation and complete audio through a backup transaction`() {
        val source = temporary.resolve("pc")
        val destination = temporary.resolve("phone")
        val remote = ArticleStore(source).create(JSONObject().put("title", "翻訳補完").put("url", "https://example.com/fill")
            .put("paragraphs", JSONArray(listOf("本文。"))).put("translated_paragraphs", JSONArray(listOf("正文。")))
            .put("image_paths", JSONArray(listOf("media/写真.jpg"))), "2026-10-17",
            listOf(StoredMedia("media/写真.jpg", byteArrayOf(1, 2, 3), "image", caption = "写真", sourceUrl = "https://example.com/image.jpg")))
        val local = ArticleStore(destination).create(JSONObject().put("title", "翻訳補完").put("url", "https://example.com/fill")
            .put("paragraphs", JSONArray(listOf("本文。"))).put("translated_paragraphs", JSONArray(listOf(""))), "2026-10-17")
        Files.write(source.resolve(remote.directory).resolve("audio/七海.mp3"), byteArrayOf(1, 2, 3))
        val zip = temporary.resolve("fill.zip")
        LibrarySyncStore(source).exportBundle("article:${remote.metadata.getString("storage_key")}", zip)
        assertEquals("updated", LibrarySyncStore(destination).importBundle(zip).getString("status"))
        val saved = ArticleCatalog(destination).find(local.metadata.getLong("id"))
        assertEquals("正文。", saved.metadata.getJSONArray("translated_paragraphs").getString(0))
        assertEquals("media/写真.jpg", saved.metadata.getJSONArray("image_paths").getString(0))
        assertArrayEquals(byteArrayOf(1, 2, 3), Files.readAllBytes(destination.resolve(saved.directory).resolve("audio/七海.mp3")))
        assertTrue(Files.list(destination.resolve("backups")).use { it.findAny().isPresent })
    }

    @Test fun `existing book gains missing translation and keeps local reading progress`() {
        val destination = temporary.resolve("phone")
        val store = LibrarySyncStore(destination)
        val fixture = Path.of("../../tests/fixtures/sync-v2/book.zip")
        store.importBundle(fixture)
        val folder = destination.resolve("books/同期の本")
        val chapter = SyncFiles.json(folder.resolve("chapters/0001.json"))
        chapter.getJSONArray("blocks").getJSONObject(0).put("text_zh", "")
        SyncFiles.writeJson(folder.resolve("chapters/0001.json"), chapter)
        val meta = SyncFiles.json(folder.resolve("book.json"))
        meta.getJSONObject("book").getJSONArray("chapters").getJSONObject(0).put("sha256", SyncFiles.hash(folder.resolve("chapters/0001.json")))
        SyncFiles.writeJson(folder.resolve("book.json"), meta)
        assertEquals("updated", store.importBundle(fixture).getString("status"))
        assertEquals("书的正文。", SyncFiles.json(folder.resolve("chapters/0001.json")).getJSONArray("blocks").getJSONObject(0).getString("text_zh"))
    }

    @Test fun `unsafe article furigana is rejected before any sync content is exposed`() {
        val root = temporary.resolve("pc")
        val item = ArticleStore(root).create(JSONObject().put("title", "危険な注音").put("url", "https://example.com/unsafe")
            .put("paragraphs", JSONArray(listOf("本文。")))
            .put("furigana_paragraphs", JSONArray(listOf("<img src=x onerror=alert(1)>"))), "2026-10-17")
        assertThrows(Exception::class.java) { LibrarySyncStore(root).exportBundle("article:${item.metadata.getString("storage_key")}", temporary.resolve("unsafe.zip")) }
    }
}
