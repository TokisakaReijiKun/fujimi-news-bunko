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
            projection.execSQL("PRAGMA case_sensitive_like=ON")
            if (projection.version != 2) {
                projection.beginTransaction()
                try {
                    projection.execSQL("DROP TABLE IF EXISTS search_entries")
                    projection.execSQL("DROP TABLE IF EXISTS search_subdetails")
                    projection.execSQL("CREATE TABLE search_entries (record_id INTEGER PRIMARY KEY,spell TEXT,normalized TEXT,pron TEXT,excerpt TEXT,romaji_hepburn_CN TEXT)")
                    projection.execSQL("CREATE TABLE search_subdetails (pk TEXT PRIMARY KEY,word_id INTEGER,title TEXT,ordinal INTEGER)")
                    val insert = projection.compileStatement("INSERT INTO search_entries VALUES (?,?,?,?,?,?)")
                    val subInsert = projection.compileStatement("INSERT INTO search_subdetails VALUES (?,?,?,?)")
                    insert.use { statement ->
                      subInsert.use { definition ->
                        var ordinal = 0L
                        originalDb().rawQuery("SELECT record_id,spell,normalized,pron,excerpt,detail_json FROM entries ORDER BY record_id", null).use { cursor ->
                            while (cursor.moveToNext()) {
                                statement.clearBindings()
                                val id = cursor.getLong(0)
                                val word = JSONObject(cursor.getString(5))
                                statement.bindLong(1, id)
                                for (column in 1..4) statement.bindString(column + 1, cursor.getString(column) ?: "")
                                statement.bindString(6, word.optString("romaji"))
                                statement.executeInsert()
                                val meanings = word.optJSONArray("definitions") ?: JSONArray()
                                for (index in 0 until meanings.length()) {
                                    val meaning = meanings.getJSONObject(index)
                                    definition.clearBindings()
                                    definition.bindString(1, "$id:${meaning.optString("id", index.toString())}")
                                    definition.bindLong(2, id)
                                    definition.bindString(3, meaning.optString("title"))
                                    definition.bindLong(4, ordinal++)
                                    definition.executeInsert()
                                }
                            }
                        }
                      }
                    }
                    projection.execSQL("CREATE INDEX IF NOT EXISTS search_spell ON search_entries(spell COLLATE NOCASE)")
                    projection.execSQL("CREATE INDEX IF NOT EXISTS search_normalized ON search_entries(normalized COLLATE NOCASE)")
                    projection.execSQL("CREATE INDEX IF NOT EXISTS search_pron ON search_entries(pron COLLATE NOCASE)")
                    projection.execSQL("CREATE INDEX search_spell_exact ON search_entries(spell)")
                    projection.execSQL("CREATE INDEX search_pron_exact ON search_entries(pron)")
                    projection.execSQL("CREATE INDEX search_romaji ON search_entries(romaji_hepburn_CN)")
                    projection.execSQL("CREATE INDEX search_subdetail_title ON search_subdetails(title)")
                    projection.version = 2
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
    fun request(method: String, pathWithQuery: String, body: String? = null): ApiResponse? {
        val path = pathWithQuery.substringBefore('?')
        if (method == "POST" && path == "/api/dictionary/tokenize") {
            return try {
                val texts = JSONObject(body ?: "{}").getJSONArray("texts")
                require(texts.length() <= 10000)
                val tokens = JSONArray()
                for (index in 0 until texts.length()) {
                    val text = texts.getString(index); require(text.length <= 100000)
                    tokens.put(JSONArray(MojiLookupTokenizer.surfaces(text)))
                }
                ApiResponse(200, JSONObject().put("tokens", tokens).toString())
            } catch (_: Exception) { ApiResponse(400, "{\"detail\":\"文章分词失败。\"}") }
        }
        if (method != "GET") return null
        return try {
            when {
                path == "/api/dictionary/stats" -> ApiResponse(200, JSONObject()
                    .put("entries", db().rawQuery("SELECT count(*) FROM search_entries", null).use { it.moveToFirst(); it.getLong(0) })
                    .put("dictionary", "日中辞典").toString())
                path == "/api/dictionary/search" -> search(pathWithQuery)
                path == "/api/dictionary/clickDetail" -> clickDetail(pathWithQuery)
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
            return ApiResponse(200, MojiLocalDictionaryAdapter.response(JSONObject(cursor.getString(0))).toString())
        }
    }

    private fun clickDetail(pathWithQuery: String): ApiResponse {
        val query = URLDecoder.decode(pathWithQuery.substringAfter("q=", "").substringBefore('&'), "UTF-8")
            .substringBefore('(')
        val match = MojiOfflineSearch.search(query, ::queryRows)
            ?: return ApiResponse(404, "{\"detail\":\"无查询结果\"}")
        return detail((match.row.ownerPk ?: match.row.pk).toLong())
    }

    /** Only Realm's storage operations are adapted; query generation/ranking is the original port. */
    private fun queryRows(query: MojiOfflineSearch.Query, limit: Int): List<MojiOfflineSearch.Row> {
        require(!query.ignoreCase && query.operation in setOf("EQUAL", "LIKE"))
        val subdetails = query.model == "Subdetails"
        require(if (subdetails) query.field == "title" else query.model == "Wort" && query.field in setOf("spell", "pron", "romaji_hepburn_CN"))
        val field = if (subdetails) "s.title" else "w.${query.field}"
        val expression = if (query.operation == "EQUAL") "$field = ? COLLATE BINARY" else "$field LIKE ? ESCAPE '\\'"
        val value = if (query.operation == "EQUAL") query.value else query.value.replace("\\", "\\\\")
            .replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_")
        val sql = if (subdetails) "SELECT s.pk,w.record_id,w.spell,w.pron,w.excerpt,s.ordinal FROM search_subdetails s JOIN search_entries w ON w.record_id=s.word_id WHERE $expression ORDER BY s.ordinal LIMIT ?"
            else "SELECT CAST(w.record_id AS TEXT),w.record_id,w.spell,w.pron,w.excerpt,w.record_id FROM search_entries w WHERE $expression ORDER BY w.record_id LIMIT ?"
        return db().rawQuery(sql, arrayOf(value, limit.toString())).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    val spell = cursor.getString(2).orEmpty()
                    val pron = cursor.getString(3).orEmpty()
                    add(MojiOfflineSearch.Row(cursor.getString(0), query.model,
                        if (subdetails) cursor.getLong(1).toString() else null,
                        spell.ifEmpty { pron }, cursor.getString(4).orEmpty(), cursor.getLong(5)))
                }
            }
        }
    }

    @Synchronized fun close() { database?.close(); original?.close(); database = null; original = null }
}
