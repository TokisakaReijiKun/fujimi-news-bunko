package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.Executors
import jp.fujimi.newsbunko.next.daily.StoredMedia

class ArticleStoreTest {
    @TempDir lateinit var data: Path

    @Test fun writesPcTextFormatAndPreservesCodePointSpans() {
        val article = ArticleStore(data).create(input("https://example.test/one", "今日の😀新聞"), "2026-10-01")
        val loaded = ArticleReader(data).load(article.directory)
        assertEquals("articles/2026-10-01/今日の😀新聞", loaded.directory)
        assertEquals(listOf("今日は😀。", "明日です。"), loaded.paragraphs)
        assertEquals(listOf("今天😀。", "明天。"), strings(loaded.metadata.getJSONArray("translated_paragraphs")))
        assertFalse(loaded.manifest.getJSONObject("article").has("paragraphs"))
        assertEquals(1, loaded.manifest.getInt("revision"))
        assertTrue(Files.isDirectory(data.resolve(loaded.directory).resolve("media")))
        assertTrue(Files.isDirectory(data.resolve(loaded.directory).resolve("audio")))
    }

    @Test fun sameDayUrlIsReusedAndOtherDayGetsIndependentId() {
        val one = ArticleStore(data).create(input("https://example.test/one", "元のタイトル"), "2026-10-01")
        val same = ArticleStore(data).create(input("https://example.test/one", "変更タイトル"), "2026-10-01")
        val other = ArticleStore(data).create(input("https://example.test/one", "元のタイトル"), "2026-10-02")
        assertEquals(one.directory, same.directory)
        assertEquals("元のタイトル", same.metadata.getString("title"))
        assertNotEquals(one.metadata.getLong("id"), other.metadata.getLong("id"))
        assertEquals(listOf("2026-10-02"), strings(other.metadata.getJSONArray("edition_dates")))
    }

    @Test fun titleCollisionUsesPcNumericSuffixWithoutOverwriting() {
        val store = ArticleStore(data)
        val first = store.create(input("https://example.test/one", "同名"), "2026-10-01")
        val second = store.create(input("https://example.test/two", "同名"), "2026-10-01")
        assertEquals("articles/2026-10-01/同名", first.directory)
        assertEquals("articles/2026-10-01/同名--${second.metadata.getLong("id")}", second.directory)
        assertEquals("https://example.test/one", ArticleReader(data).load(first.directory).metadata.getString("url"))
    }

    @Test fun separateStoreInstancesSerializeNumericIds() {
        val pool = Executors.newFixedThreadPool(4)
        try {
            val work = (1..12).map { number -> pool.submit<Long> {
                ArticleStore(data).create(input("https://example.test/$number", "同名"), "2026-10-01").metadata.getLong("id")
            } }
            val ids = work.map { it.get() }
            assertEquals(12, ids.toSet().size)
            assertEquals(12, ArticleCatalog(data).onDay("2026-10-01").size)
        } finally { pool.shutdownNow() }
    }

    @Test fun cancelledStagingNeverCreatesAnArticleAndRecoveryIsRepeatable() {
        val store = ArticleStore(data)
        var checkpoints = 0
        assertThrows(java.util.concurrent.CancellationException::class.java) {
            store.create(input("https://example.test/one", "中止"), "2026-10-01", checkpoint = {
                if (++checkpoints == 3) throw java.util.concurrent.CancellationException("中止")
            })
        }
        ArticleStore(data).recover()
        ArticleStore(data).recover()
        assertTrue(ArticleCatalog(data).onDay("2026-10-01").isEmpty())
    }

    @Test fun recoversCommittedPcJournalAndDiscardsUncommittedStage() {
        val committed = ArticleStore(data).create(input("https://example.test/one", "已提交"), "2026-10-01")
        val completed = data.resolve("diagnostics/transactions/finished")
        Files.createDirectories(completed)
        Files.writeString(completed.resolve("journal.json"), JSONObject().put("target", committed.directory.removePrefix("articles/")).toString())
        val abandoned = data.resolve("diagnostics/transactions/abandoned")
        Files.createDirectories(abandoned.resolve("new"))
        Files.writeString(abandoned.resolve("journal.json"), JSONObject().put("target", "2026-10-01/未提交").toString())
        ArticleStore(data).recover()
        ArticleStore(data).recover()
        assertFalse(Files.exists(completed))
        assertFalse(Files.exists(abandoned))
        assertEquals("已提交", ArticleReader(data).load(committed.directory).metadata.getString("title"))
    }

    @Test fun rejectsMisalignedTranslationBeforeExposingFiles() {
        val invalid = input("https://example.test/one", "失配")
            .put("translated_paragraphs", JSONArray(listOf("一段")))
        assertThrows(IllegalArgumentException::class.java) { ArticleStore(data).create(invalid, "2026-10-01") }
        assertTrue(ArticleCatalog(data).onDay("2026-10-01").isEmpty())
    }

    @Test fun registersDownloadedMediaAndRejectsTraversalBeforeAnyArticleIsCreated() {
        val store = ArticleStore(data)
        assertThrows(IllegalArgumentException::class.java) {
            store.create(input("https://example.test/unsafe", "不安全"), "2026-10-01",
                listOf(StoredMedia("media/../outside.jpg", byteArrayOf(1), "image")))
        }
        assertTrue(ArticleCatalog(data).onDay("2026-10-01").isEmpty())
        val metadata = input("https://example.test/safe", "画像").put("image_paths", JSONArray(listOf("media/image.jpg")))
        val saved = store.create(metadata, "2026-10-01",
            listOf(StoredMedia("media/image.jpg", byteArrayOf(1, 2, 3), "image", "图注", 0, "https://example.test/image.jpg")))
        val asset = saved.manifest.getJSONArray("assets").getJSONObject(0)
        assertEquals("media/image.jpg", asset.getString("path"))
        assertEquals(3, asset.getInt("bytes"))
        assertEquals("图注", asset.getString("caption"))
        assertArrayEquals(byteArrayOf(1, 2, 3), Files.readAllBytes(data.resolve(saved.directory).resolve("media/image.jpg")))
        assertEquals(listOf("media/image.jpg"), strings(ArticleReader(data).load(saved.directory).metadata.getJSONArray("image_paths")))
    }

    @Test fun importedPcNumericIdAdvancesPhoneSequenceAndReservedTitlesAreSafe() {
        val imported = ArticleStore(data).create(input("https://example.test/imported", "同步文章"), "2026-10-01")
        val file = data.resolve(imported.directory).resolve("article.json")
        val manifest = JSONObject(Files.readString(file))
        manifest.getJSONObject("article").put("id", 700)
        Files.writeString(file, manifest.toString())
        val phone = ArticleStore(data).create(input("https://example.test/phone", "CON.txt"), "2026-10-01")
        assertEquals(701L, phone.metadata.getLong("id"))
        assertEquals("articles/2026-10-01/_CON.txt", phone.directory)
    }

    @Test fun pcLeadingImagePositionMinusOneIsPreservedAsAnArticleCover() {
        val metadata = input("https://example.test/cover", "首图")
            .put("image_paths", JSONArray(listOf("media/cover.jpg")))
            .put("image_positions", JSONArray(listOf(-1)))
        val saved = ArticleStore(data).create(metadata, "2026-10-01",
            listOf(StoredMedia("media/cover.jpg", byteArrayOf(1, 2, 3), "image", paragraphIndex = -1)))
        val loaded = ArticleReader(data).load(saved.directory)
        assertEquals(-1, loaded.metadata.getJSONArray("image_positions").getInt(0))
        assertEquals(-1, loaded.manifest.getJSONArray("assets").getJSONObject(0).getInt("position"))
    }

    @Test fun cancelledIdsAreNotReusedAfterAnotherStoreRestarts() {
        var calls = 0
        assertThrows(java.util.concurrent.CancellationException::class.java) {
            ArticleStore(data).create(input("https://example.test/one", "已取消"), "2026-10-01", checkpoint = {
                if (++calls == 2) throw java.util.concurrent.CancellationException("中止")
            })
        }
        val next = ArticleStore(data).create(input("https://example.test/two", "下一篇"), "2026-10-01")
        assertEquals(2L, next.metadata.getLong("id"))
    }

    @Test fun corruptCommittedArticleKeepsRecoveryJournalInsteadOfPretendingRecoverySucceeded() {
        val saved = ArticleStore(data).create(input("https://example.test/one", "损坏事务"), "2026-10-01")
        val transaction = data.resolve("diagnostics/transactions/corrupt-commit")
        Files.createDirectories(transaction)
        Files.writeString(transaction.resolve("journal.json"), JSONObject().put("target", saved.directory.removePrefix("articles/")).toString())
        Files.writeString(data.resolve(saved.directory).resolve("original.txt"), "corrupted externally")
        assertThrows(ArticleFormatException::class.java) { ArticleStore(data).recover() }
        assertTrue(Files.exists(transaction.resolve("journal.json")))
    }

    @Test fun recoveredTargetCannotBelongToAnUnrelatedArticleOrDiscardItsRecoverableOldVersion() {
        val first = ArticleStore(data).create(input("https://example.test/one", "无关目标"), "2026-10-01")
        val second = ArticleStore(data).create(input("https://example.test/two", "需恢复文章"), "2026-10-01")
        val transaction = data.resolve("diagnostics/transactions/conflicting-commit")
        Files.createDirectories(transaction)
        Files.move(data.resolve(second.directory), transaction.resolve("old"))
        Files.writeString(transaction.resolve("journal.json"), JSONObject().put("target", first.directory.removePrefix("articles/"))
            .put("article_id", second.metadata.getLong("id")).toString())
        assertThrows(ArticleFormatException::class.java) { ArticleStore(data).recover() }
        assertTrue(Files.exists(transaction.resolve("old/article.json")))
        assertTrue(Files.exists(transaction.resolve("journal.json")))
        assertEquals("https://example.test/one", ArticleReader(data).load(first.directory).metadata.getString("url"))
    }

    @Test fun sequenceFloorFromPcOrTheAndroidIndexAdvancesIdsAndCannotMoveBackwards() {
        assertEquals(900L, ArticleStore(data).advanceSequenceFloor(900))
        assertEquals(900L, ArticleStore(data).advanceSequenceFloor(800))
        val first = ArticleStore(data).create(input("https://example.test/floor-one", "索引高序号"), "2026-10-01")
        assertEquals(900L, first.metadata.getLong("id"))
        assertEquals(901L, ArticleStore(data).advanceSequenceFloor(500))
        val next = ArticleStore(data).create(input("https://example.test/floor-two", "索引重启"), "2026-10-01")
        assertEquals(901L, next.metadata.getLong("id"))
        assertThrows(IllegalArgumentException::class.java) { ArticleStore(data).advanceSequenceFloor(0) }
    }

    private fun input(url: String, title: String) = JSONObject()
        .put("url", url).put("title", title).put("source_name", "NHKニュース")
        .put("paragraphs", JSONArray(listOf("今日は😀。", "明日です。")))
        .put("translated_paragraphs", JSONArray(listOf("今天😀。", "明天。")))
        .put("furigana_paragraphs", JSONArray())

    private fun strings(array: JSONArray) = (0 until array.length()).map { array.getString(it) }
}
