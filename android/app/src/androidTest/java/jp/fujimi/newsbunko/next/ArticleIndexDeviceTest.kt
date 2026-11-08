package jp.fujimi.newsbunko.next

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import jp.fujimi.newsbunko.next.daily.AndroidArticleIndex
import jp.fujimi.newsbunko.next.store.ArticleReader
import jp.fujimi.newsbunko.next.store.ArticleStore
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.nio.file.Files

@RunWith(AndroidJUnit4::class)
class ArticleIndexDeviceTest {
    @Test fun databaseAndFileSequencesRetainBothSidesHistory() = temporary { data ->
        val store = ArticleStore(data.toPath())
        val first = store.create(article("one"), "2026-10-01")
        SQLiteDatabase.openOrCreateDatabase(java.io.File(data, "fujimi.sqlite3"), null).use { database ->
            database.execSQL("CREATE TABLE article_sequence(singleton INTEGER PRIMARY KEY, next_id INTEGER NOT NULL)")
            database.execSQL("INSERT INTO article_sequence VALUES(1,100)")
        }
        AndroidArticleIndex(data).rebuild()
        val second = store.create(article("two"), "2026-10-01")
        assertEquals(100L, second.metadata.getLong("id"))
        // Cancellation after allocating an ID must leave the gap reserved for PC as well.
        var checks = 0
        try {
            store.create(article("cancelled"), "2026-10-01", checkpoint = {
                if (++checks == 2) throw java.util.concurrent.CancellationException()
            })
            fail("Expected cancellation after ID reservation")
        } catch (_: java.util.concurrent.CancellationException) { }
        val reserved = JSONObject(java.io.File(data, "diagnostics/article-sequence.json").readText()).getLong("next_id")
        assertTrue(reserved > 101)
        AndroidArticleIndex(data).rebuild()
        SQLiteDatabase.openDatabase(java.io.File(data, "fujimi.sqlite3").path, null, SQLiteDatabase.OPEN_READONLY).use { database ->
            database.rawQuery("SELECT next_id FROM article_sequence", null).use { cursor -> assertTrue(cursor.moveToFirst()); assertEquals(reserved, cursor.getLong(0)) }
            database.rawQuery("PRAGMA table_info(articles)", null).use { cursor ->
                val names = mutableListOf<String>()
                while (cursor.moveToNext()) names += cursor.getString(1)
                assertFalse(names.contains("payload"))
            }
        }
        assertEquals(listOf("今日のニュース。"), ArticleReader(data.toPath()).load(first.directory).paragraphs)
    }

    @Test fun onlyBookmarkCopyAlsoReservesItsOriginalNumericId() = temporary { data ->
        val bookmark = java.io.File(data, "bookmarks/保存した記事").also { it.mkdirs() }
        java.io.File(bookmark, "article.json").writeText(JSONObject().put("schema_version", 1)
            .put("article", JSONObject().put("id", 700)).toString())
        AndroidArticleIndex(data).rebuild()
        val created = ArticleStore(data.toPath()).create(article("after-bookmark"), "2026-10-01")
        assertEquals(701L, created.metadata.getLong("id"))
        assertTrue(bookmark.exists())
    }

    @Test fun invalidIndexSchemaDoesNotDiscardCommittedArticleFiles() = temporary { data ->
        val saved = ArticleStore(data.toPath()).create(article("saved"), "2026-10-01")
        val bytes = java.io.File(data, "${saved.directory}/original.txt").readBytes()
        SQLiteDatabase.openOrCreateDatabase(java.io.File(data, "fujimi.sqlite3"), null).use { database ->
            database.execSQL("CREATE TABLE articles(legacy_marker TEXT)")
            database.execSQL("INSERT INTO articles VALUES('preserve-before-failure')")
        }
        try { AndroidArticleIndex(data).rebuild(); fail("An incompatible index must be reported") }
        catch (_: android.database.sqlite.SQLiteException) { }
        assertArrayEquals(bytes, java.io.File(data, "${saved.directory}/original.txt").readBytes())
        assertEquals(listOf("今日のニュース。"), ArticleReader(data.toPath()).load(saved.directory).paragraphs)
        SQLiteDatabase.openDatabase(java.io.File(data, "fujimi.sqlite3").path, null, SQLiteDatabase.OPEN_READONLY).use { database ->
            database.rawQuery("SELECT legacy_marker FROM articles", null).use { cursor -> assertTrue(cursor.moveToFirst()); assertEquals("preserve-before-failure", cursor.getString(0)) }
        }
    }

    private fun article(suffix: String) = JSONObject().put("title", "記事-$suffix")
        .put("url", "https://example.test/$suffix").put("source_name", "fixture")
        .put("paragraphs", JSONArray(listOf("今日のニュース。")))

    private fun temporary(work: (java.io.File) -> Unit) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val folder = Files.createTempDirectory(context.cacheDir.toPath(), "article-index-").toFile()
        try { work(folder) } finally { folder.deleteRecursively() }
    }
}
