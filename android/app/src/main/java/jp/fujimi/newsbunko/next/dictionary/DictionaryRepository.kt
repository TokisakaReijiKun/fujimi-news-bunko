package jp.fujimi.newsbunko.next.dictionary

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import jp.fujimi.newsbunko.next.store.ApiResponse
import jp.fujimi.newsbunko.next.storage.DataDirectory
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLDecoder
import java.nio.file.Files
import java.security.MessageDigest

class DictionaryRepository(private val context: Context) {
    private val databaseFile = File(DataDirectory.root(), "dictionary-search.sqlite3")
    private val originalFile = File(context.filesDir, "dictionary/dictionary.sqlite3")
    private var database: SQLiteDatabase? = null
    private var original: SQLiteDatabase? = null

    @Synchronized
    private fun db(): SQLiteDatabase {
        database?.let { if (it.isOpen) return it }
        originalDb()
        databaseFile.parentFile?.mkdirs()
        val projection = SQLiteDatabase.openOrCreateDatabase(databaseFile, null)
        try {
            if (projection.version != 1) {
                projection.beginTransaction()
                try {
                    projection.execSQL("CREATE TABLE IF NOT EXISTS search_entries (record_id INTEGER PRIMARY KEY,spell TEXT,normalized TEXT,pron TEXT,excerpt TEXT)")
                    projection.execSQL("DELETE FROM search_entries")
                    val insert = projection.compileStatement("INSERT INTO search_entries VALUES (?,?,?,?,?)")
                    insert.use { statement ->
                        originalDb().rawQuery("SELECT record_id,spell,normalized,pron,excerpt FROM entries", null).use { cursor ->
                            while (cursor.moveToNext()) {
                                statement.clearBindings()
                                statement.bindLong(1, cursor.getLong(0))
                                for (column in 1..4) statement.bindString(column + 1, cursor.getString(column) ?: "")
                                statement.executeInsert()
                            }
                        }
                    }
                    projection.execSQL("CREATE INDEX IF NOT EXISTS search_spell ON search_entries(spell COLLATE NOCASE)")
                    projection.execSQL("CREATE INDEX IF NOT EXISTS search_normalized ON search_entries(normalized COLLATE NOCASE)")
                    projection.execSQL("CREATE INDEX IF NOT EXISTS search_pron ON search_entries(pron COLLATE NOCASE)")
                    projection.version = 1
                    projection.setTransactionSuccessful()
                } finally { projection.endTransaction() }
            }
            database = projection
            return projection
        } catch (error: Exception) { projection.close(); throw error }
    }

    private fun originalDb(): SQLiteDatabase {
        original?.let { if (it.isOpen) return it }
        originalFile.parentFile?.mkdirs()
        if (!originalFile.isFile || originalFile.length() != 319164416L) {
            val temporary = File(originalFile.parentFile, "dictionary.sqlite3.tmp")
            try {
                val digest = MessageDigest.getInstance("SHA-256")
                context.assets.open("dictionary/dictionary.sqlite3").use { input ->
                    temporary.outputStream().use { output ->
                        val buffer = ByteArray(64 * 1024)
                        while (true) {
                            val length = input.read(buffer)
                            if (length < 0) break
                            digest.update(buffer, 0, length)
                            output.write(buffer, 0, length)
                        }
                    }
                }
                check(digest.digest().joinToString("") { "%02x".format(it) } == "751943f8f969f4ff8997ebbfd24a5b0d20b7b99557602e0702c61da4d33eafdd")
                Files.move(temporary.toPath(), originalFile.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
                originalFile.setReadOnly()
            } finally { temporary.delete() }
        }
        return SQLiteDatabase.openDatabase(originalFile.path, null, SQLiteDatabase.OPEN_READONLY).also { original = it }
    }

    @Synchronized
    fun request(method: String, pathWithQuery: String): ApiResponse? {
        if (method != "GET") return null
        val path = pathWithQuery.substringBefore('?')
        return try {
            when {
                path == "/api/dictionary/stats" -> ApiResponse(200, JSONObject()
                    .put("entries", db().rawQuery("SELECT count(*) FROM search_entries", null).use { it.moveToFirst(); it.getLong(0) })
                    .put("dictionary", "日中辞典").toString())
                path == "/api/dictionary/search" -> search(pathWithQuery)
                Regex("/api/dictionary/words/\\d+").matches(path) -> detail(path.substringAfterLast('/').toLong())
                else -> null
            }
        } catch (error: Exception) {
            ApiResponse(503, JSONObject().put("detail", "词库暂时无法读取，请重试。").toString())
        }
    }

    private fun search(pathWithQuery: String): ApiResponse {
        val raw = pathWithQuery.substringAfter("q=", "").substringBefore('&')
        val query = URLDecoder.decode(raw, "UTF-8").trim().take(100)
        if (query.isEmpty()) return ApiResponse(200, JSONObject().put("results", JSONArray()).toString())
        val escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        val rows = db().rawQuery(
            "SELECT record_id,spell,pron,excerpt FROM search_entries WHERE spell=? OR normalized=? OR pron=? " +
                "OR spell LIKE ? ESCAPE '\\' OR pron LIKE ? ESCAPE '\\' OR normalized LIKE ? ESCAPE '\\' LIMIT 30",
            arrayOf(query, query.lowercase(), query, "$escaped%", "$escaped%", "${escaped.lowercase()}%"),
        ).use { cursor ->
            val result = JSONArray()
            val id = cursor.getColumnIndexOrThrow("record_id")
            val spell = cursor.getColumnIndexOrThrow("spell")
            val pron = cursor.getColumnIndexOrThrow("pron")
            val excerpt = cursor.getColumnIndexOrThrow("excerpt")
            while (cursor.moveToNext()) result.put(JSONObject()
                .put("id", cursor.getString(id)).put("spell", cursor.getString(spell))
                .put("pron", cursor.getString(pron)).put("excerpt", cursor.getString(excerpt)))
            result
        }
        return ApiResponse(200, JSONObject().put("results", rows).toString())
    }

    private fun detail(id: Long): ApiResponse {
        originalDb().rawQuery("SELECT detail_json FROM entries WHERE record_id=?", arrayOf(id.toString())).use { cursor ->
            if (!cursor.moveToFirst()) return ApiResponse(404, JSONObject().put("detail", "词条不存在。").toString())
            return ApiResponse(200, cursor.getString(0))
        }
    }

    @Synchronized fun close() { database?.close(); original?.close(); database = null; original = null }
}
