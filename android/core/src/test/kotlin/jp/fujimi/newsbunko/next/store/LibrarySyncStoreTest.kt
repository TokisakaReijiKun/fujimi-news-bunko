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
import jp.fujimi.newsbunko.next.daily.StoredMedia

class LibrarySyncStoreTest {
    @TempDir lateinit var temporary: Path

    private fun article(root: Path, title: String, text: String) = ArticleStore(root).create(JSONObject()
        .put("title", title).put("url", "https://example.com/$title").put("paragraphs", JSONArray(listOf(text))), "2026-10-17")

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
