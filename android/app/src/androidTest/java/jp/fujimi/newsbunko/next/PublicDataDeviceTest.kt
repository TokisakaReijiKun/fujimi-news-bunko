package jp.fujimi.newsbunko.next

import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import jp.fujimi.newsbunko.next.daily.AndroidArticleIndex
import jp.fujimi.newsbunko.next.store.ArticleReader
import jp.fujimi.newsbunko.next.store.ArticleStore
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.nio.file.Files

@RunWith(AndroidJUnit4::class)
class PublicDataDeviceTest {
    @Test fun publicLibrarySupportsArticleTransactionsAndSqlite() {
        var path = ""
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { path = JSONObject(it.bridge.mobileStatus()).getString("data_path") }
        }
        assertEquals("/storage/emulated/0/富士見新聞文庫/data", path)
        val diagnostics = File(path, "diagnostics").also { assertTrue(it.isDirectory || it.mkdirs()) }
        val temporary = Files.createTempDirectory(diagnostics.toPath(), "storage-test-").toFile()
        try {
            val saved = ArticleStore(temporary.toPath()).create(JSONObject()
                .put("title", "東京のニュース").put("url", "https://example.test/public-storage")
                .put("source_name", "fixture").put("paragraphs", JSONArray(listOf("今日のニュース。"))), "2026-10-02")
            assertEquals("articles/2026-10-02/東京のニュース", saved.directory)
            assertTrue(File(temporary, "${saved.directory}/article.json").isFile)
            assertTrue(File(temporary, "${saved.directory}/original.txt").isFile)
            assertEquals(listOf("今日のニュース。"), ArticleReader(temporary.toPath()).load(saved.directory).paragraphs)
            AndroidArticleIndex(temporary).rebuild()
            SQLiteDatabase.openDatabase(File(temporary, "fujimi.sqlite3").path, null, SQLiteDatabase.OPEN_READONLY).use { database ->
                database.rawQuery("SELECT title FROM articles", null).use { cursor ->
                    assertTrue(cursor.moveToFirst())
                    assertEquals("東京のニュース", cursor.getString(0))
                }
            }
        } finally { temporary.deleteRecursively() }
    }
}
