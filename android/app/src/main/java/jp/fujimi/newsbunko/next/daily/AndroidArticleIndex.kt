package jp.fujimi.newsbunko.next.daily

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import jp.fujimi.newsbunko.next.store.ArticleCatalog
import jp.fujimi.newsbunko.next.store.ArticleStore
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption

/** PC-compatible rebuildable index at data/fujimi.sqlite3. Never stores body text. */
class AndroidArticleIndex(private val dataRoot: File) {
    @Synchronized fun rebuild() {
        ArticleStore(dataRoot.toPath()).recover()
        val catalog = ArticleCatalog(dataRoot.toPath())
        val articles = catalog.days().flatMap(catalog::onDay)
        require(articles.map { it.metadata.getLong("id") }.distinct().size == articles.size) { "不同文章使用了相同 ID，索引重建已停止。" }
        val keys = articles.map { it.metadata.optString("storage_key").ifBlank { it.metadata.optString("url").ifBlank { "local:${it.metadata.getLong("id")}" } } }
        require(keys.distinct().size == keys.size) { "不同文章使用了相同身份，索引重建已停止。" }
        dataRoot.mkdirs()
        SQLiteDatabase.openOrCreateDatabase(File(dataRoot, "fujimi.sqlite3"), null).use { database ->
            database.execSQL("CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY,url TEXT UNIQUE NOT NULL,directory TEXT UNIQUE NOT NULL,title TEXT NOT NULL,source_name TEXT NOT NULL,status TEXT NOT NULL,bookmarked INTEGER NOT NULL,created_at TEXT,revision INTEGER NOT NULL)")
            database.execSQL("CREATE TABLE IF NOT EXISTS article_days(article_id INTEGER NOT NULL,day TEXT NOT NULL,PRIMARY KEY(article_id,day))")
            database.execSQL("CREATE TABLE IF NOT EXISTS article_sequence(singleton INTEGER PRIMARY KEY CHECK(singleton=1),next_id INTEGER NOT NULL)")
            database.execSQL("INSERT OR IGNORE INTO article_sequence VALUES(1,1)")
            val databaseNext = database.rawQuery("SELECT next_id FROM article_sequence WHERE singleton=1", null).use { cursor ->
                check(cursor.moveToFirst()) { "文章序号缺失。" }; cursor.getLong(0).also { require(it > 0) }
            }
            // Retain allocation gaps from either writer. A bookmark-only copy also owns its ID.
            // This reads sequence metadata only; database body text is never a recovery source.
            val nextId = ArticleStore(dataRoot.toPath()).advanceSequenceFloor(maxOf(databaseNext, bookmarkNextId()))
            database.beginTransaction()
            try {
                database.delete("article_days", null, null)
                database.delete("articles", null, null)
                articles.forEachIndexed { index, snapshot ->
                    val article = snapshot.metadata
                    val values = ContentValues().apply {
                        put("id", article.getLong("id")); put("url", keys[index]); put("directory", snapshot.directory.removePrefix("articles/"))
                        put("title", article.getString("title")); put("source_name", article.optString("source_name"))
                        put("status", article.optString("status", "ready")); put("bookmarked", if (article.optBoolean("bookmarked")) 1 else 0)
                        put("created_at", article.optString("created_at")); put("revision", article.getInt("_revision"))
                    }
                    database.insertOrThrow("articles", null, values)
                    val days = article.getJSONArray("edition_dates")
                    for (day in 0 until days.length()) database.insertOrThrow("article_days", null, ContentValues().apply { put("article_id", article.getLong("id")); put("day", days.getString(day)) })
                }
                database.execSQL("UPDATE article_sequence SET next_id=MAX(next_id,?) WHERE singleton=1", arrayOf(nextId))
                database.setTransactionSuccessful()
            } finally { database.endTransaction() }
        }
    }

    private fun bookmarkNextId(): Long {
        val root = File(dataRoot, "bookmarks").toPath()
        require(!Files.isSymbolicLink(root)) { "收藏目录不能是符号链接。" }
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) return 1
        var next = 1L
        Files.list(root).use { directories -> directories.forEach { folder ->
            require(!Files.isSymbolicLink(folder)) { "收藏副本不能是符号链接。" }
            if (Files.isDirectory(folder, LinkOption.NOFOLLOW_LINKS)) {
                val file = folder.resolve("article.json")
                require(!Files.isSymbolicLink(file)) { "收藏清单不能是符号链接。" }
                val manifest = JSONObject(String(Files.readAllBytes(file), Charsets.UTF_8))
                require(manifest.getInt("schema_version") == 1)
                val id = manifest.getJSONObject("article").getLong("id").also { require(it > 0) }
                next = maxOf(next, Math.addExact(id, 1))
            }
        } }
        return next
    }
}
