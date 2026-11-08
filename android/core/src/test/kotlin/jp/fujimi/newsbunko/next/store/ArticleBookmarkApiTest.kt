package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.net.URI
import jp.fujimi.newsbunko.next.daily.StoredMedia

class ArticleBookmarkApiTest {
    @TempDir lateinit var data: Path
    private fun fixture() = ArticleStore(data).create(JSONObject().put("title", "保存する記事").put("url", "https://example.com/article")
        .put("paragraphs", JSONArray(listOf("元の本文。", "二つ目の段落。"))), "2026-11-05")

    @Test fun legacyBookmarkFlagRemainsVisibleWithoutCreatingOrRewritingCopies() {
        val article = fixture(); val id = article.metadata.getLong("id")
        val manifestPath = data.resolve(article.directory).resolve("article.json")
        val manifest = SyncFiles.json(manifestPath)
        manifest.getJSONObject("article").put("bookmarked", true)
        SyncFiles.writeJson(manifestPath, manifest)
        val before = Files.readAllBytes(manifestPath)
        val unrelated = ArticleStore(data).create(JSONObject().put("title", "別の日の未收藏記事").put("url", "https://example.com/unrelated")
            .put("paragraphs", JSONArray(listOf("本文。"))), "2026-11-04")
        Files.writeString(data.resolve(unrelated.directory).resolve("original.txt"), "外部変更")
        val api = LocalLibraryApi(data)
        val response = api.request("GET", "/api/bookmarks")
        assertEquals(200, response.status)
        assertEquals(1, JSONArray(response.body).length())
        assertEquals(id, JSONArray(response.body).getJSONObject(0).getLong("id"))
        val detail = api.request("GET", "/api/bookmarks/$id")
        assertEquals(200, detail.status)
        assertEquals("元の本文。", JSONObject(detail.body).getJSONArray("paragraphs").getString(0))
        assertArrayEquals(before, Files.readAllBytes(manifestPath))
        assertFalse(Files.exists(data.resolve("bookmarks")))
        assertEquals(200, api.request("DELETE", "/api/articles/$id/bookmarks").status)
        assertEquals(0, JSONArray(api.request("GET", "/api/bookmarks").body).length())
    }

    @Test fun bookmarkIsAnIndependentCompleteCopyAndCancellationKeepsDailyContent() {
        val article = fixture(); val id = article.metadata.getLong("id"); val api = LocalLibraryApi(data)
        val original = Files.readAllBytes(data.resolve(article.directory).resolve("original.txt"))
        assertEquals(200, api.request("POST", "/api/articles/$id/bookmarks", "{}").status)
        val copy = ArticleCatalog(data).bookmarks().single()
        assertTrue(copy.directory.startsWith("bookmarks/")); assertTrue(copy.metadata.getBoolean("bookmarked"))
        assertArrayEquals(original, Files.readAllBytes(data.resolve(copy.directory).resolve("original.txt")))
        assertEquals(1, JSONArray(api.request("GET", "/api/bookmarks").body).length())
        assertEquals(200, api.request("GET", "/api/bookmarks/$id").status)
        assertEquals(200, api.request("DELETE", "/api/articles/$id/bookmarks").status)
        assertTrue(ArticleCatalog(data).bookmarks().isEmpty())
        assertFalse(ArticleCatalog(data).find(id).metadata.getBoolean("bookmarked"))
        assertArrayEquals(original, Files.readAllBytes(data.resolve(article.directory).resolve("original.txt")))
    }

    @Test fun independentBookmarkRemainsReadableAndRemovableWithoutTheDailyDirectory() {
        val article = fixture(); val id = article.metadata.getLong("id"); val api = LocalLibraryApi(data)
        assertEquals(200, api.request("POST", "/api/articles/$id/bookmarks", "{}").status)
        Files.walk(data.resolve(article.directory)).use { paths -> paths.sorted(Comparator.reverseOrder()).forEach(Files::delete) }
        val bookmarks = JSONArray(LocalLibraryApi(data).request("GET", "/api/bookmarks").body)
        assertEquals(id, bookmarks.getJSONObject(0).getLong("id"))
        val restored = JSONObject(api.request("GET", "/api/bookmarks/$id").body)
        assertEquals("元の本文。", restored.getJSONArray("paragraphs").getString(0))
        assertEquals(200, api.request("DELETE", "/api/articles/$id/bookmarks").status)
        assertEquals(0, JSONArray(api.request("GET", "/api/bookmarks").body).length())
    }

    @Test fun pendingBookmarkCopyIsCompletedByTheExistingArticleRecovery() {
        val article = fixture(); val id = article.metadata.getLong("id")
        val store = ArticleStore(data); store.setBookmarked(id, true)
        val saved = ArticleCatalog(data).find(id)
        val copy = ArticleCatalog(data).bookmarks().single()
        Files.walk(data.resolve(copy.directory)).use { paths -> paths.sorted(Comparator.reverseOrder()).forEach(Files::delete) }
        val pending = data.resolve("diagnostics/transactions/pending-bookmark")
        Files.createDirectories(pending)
        SyncFiles.writeJson(pending.resolve("journal.json"), JSONObject().put("target", saved.directory.removePrefix("articles/"))
            .put("article_id", id).put("manifest_sha256", SyncFiles.hash(data.resolve(saved.directory).resolve("article.json"))).put("bookmark_action", true))
        store.recover()
        assertEquals(id, ArticleCatalog(data).bookmarks().single().metadata.getLong("id"))
        assertFalse(Files.exists(pending))
    }

    @Test fun bookmarkMediaAndRecordingUseTheirOwnCopyEvenWhenDailyBytesDifferOrDisappear() {
        val originalImage = byteArrayOf(1, 2, 3, 4)
        val originalAudio = byteArrayOf(5, 6, 7, 8)
        val article = ArticleStore(data).create(JSONObject().put("title", "別々の副本").put("url", "https://example.com/two-copies")
            .put("paragraphs", JSONArray(listOf("本文。"))).put("image_paths", JSONArray(listOf("media/photo.jpg")))
            .put("audio_voice_mode", "voice").put("audio_voice_id", 123), "2026-11-05",
            listOf(StoredMedia("media/photo.jpg", originalImage, "image")))
        val id = article.metadata.getLong("id")
        val dayFolder = data.resolve(article.directory)
        Files.write(dayFolder.resolve("audio/録音.wav"), originalAudio)
        val recorded = SyncFiles.json(dayFolder.resolve("article.json"))
        recorded.getJSONObject("article").put("audio_path", "audio/録音.wav")
        SyncFiles.writeJson(dayFolder.resolve("article.json"), recorded)
        ArticleStore(data).setBookmarked(id, true)
        val copy = ArticleCatalog(data).findBookmark(id)
        Files.write(dayFolder.resolve("audio/録音.wav"), byteArrayOf(9, 9, 9, 9))
        val dayImage = byteArrayOf(8, 8, 8, 8)
        Files.write(dayFolder.resolve("media/photo.jpg"), dayImage)
        val manifest = SyncFiles.json(dayFolder.resolve("article.json"))
        manifest.getJSONArray("assets").getJSONObject(0).put("sha256", SyncFiles.hash(dayImage))
        SyncFiles.writeJson(dayFolder.resolve("article.json"), manifest)
        val api = LocalLibraryApi(data)
        fun assertBookmark() {
            val bookmark = JSONObject(api.request("GET", "/api/bookmarks/$id").body)
            assertEquals("ready", bookmark.getString("audio_status"))
            assertEquals("/api/bookmarks/$id/assets/audio/録音.wav", URI(bookmark.getString("audio_path")).path)
            assertEquals("/api/bookmarks/$id/media/photo.jpg", URI(bookmark.getJSONArray("image_paths").getString(0)).path)
            assertArrayEquals(originalAudio, Files.readAllBytes(ArticleAudioAccess(data).resolve(id, "録音.wav", true)))
            assertArrayEquals(originalImage, Files.readAllBytes(ArticleMediaAccess(data).resolve(id, "photo.jpg", true)))
        }
        assertBookmark()
        val daily = JSONObject(api.request("GET", "/api/articles/$id").body)
        assertEquals("/api/articles/$id/assets/audio/録音.wav", URI(daily.getString("audio_path")).path)
        assertArrayEquals(dayImage, Files.readAllBytes(ArticleMediaAccess(data).resolve(id, "photo.jpg")))
        assertArrayEquals(byteArrayOf(9, 9, 9, 9), Files.readAllBytes(ArticleAudioAccess(data).resolve(id, "録音.wav")))
        Files.delete(data.resolve(copy.directory).resolve("audio/録音.wav"))
        assertThrows(IllegalArgumentException::class.java) { ArticleAudioAccess(data).resolve(id, "録音.wav", true) }
        Files.write(data.resolve(copy.directory).resolve("audio/録音.wav"), originalAudio)
        Files.walk(dayFolder).use { paths -> paths.sorted(Comparator.reverseOrder()).forEach(Files::delete) }
        assertBookmark()
        assertEquals(1, JSONArray(api.request("GET", "/api/bookmarks").body).length())
    }

    @Test fun deleteRecoveryValidatesBothCopiesBeforeRemovingEitherOne() {
        val article = fixture(); val id = article.metadata.getLong("id")
        val store = ArticleStore(data); store.setBookmarked(id, true)
        val copy = ArticleCatalog(data).findBookmark(id)
        val other = store.create(JSONObject().put("title", "別の記事").put("url", "https://example.com/other")
            .put("paragraphs", JSONArray(listOf("他の本文。"))), "2026-11-05")
        val pending = data.resolve("diagnostics/transactions/conflicting-delete")
        SyncFiles.copyTree(data.resolve(other.directory), pending.resolve("old"))
        SyncFiles.writeJson(pending.resolve("journal.json"), JSONObject().put("target_root", "bookmarks")
            .put("target", Path.of(copy.directory).fileName.toString()).put("article_id", id).put("delete", true))
        assertThrows(ArticleFormatException::class.java) { store.recover() }
        assertTrue(Files.exists(data.resolve(copy.directory).resolve("article.json")))
        assertTrue(Files.exists(pending.resolve("old/article.json")))
        assertTrue(Files.exists(pending.resolve("journal.json")))
        assertEquals(id, SyncFiles.json(data.resolve(copy.directory).resolve("article.json")).getJSONObject("article").getLong("id"))
    }
}
