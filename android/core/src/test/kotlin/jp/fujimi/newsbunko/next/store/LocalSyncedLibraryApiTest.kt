package jp.fujimi.newsbunko.next.store

import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest

class LocalSyncedLibraryApiTest {
    @TempDir lateinit var data: Path
    private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    private fun fixture(): Path {
        val folder = data.resolve("books/本の名前")
        Files.createDirectories(folder.resolve("chapters"))
        Files.createDirectories(folder.resolve("resources"))
        val source = "synthetic epub".toByteArray()
        Files.write(folder.resolve("original.epub"), source)
        Files.write(folder.resolve("resources/cover.png"), byteArrayOf(1, 2, 3))
        val chapter = JSONObject().put("id", 1).put("title", "第一章").put("blocks", JSONArray().put(JSONObject()
            .put("text_ja", "本文です。").put("html", "<p>本文です。</p><img data-book-asset='cover.png'><a data-book-href='chapter.xhtml#next'>次</a><script>alert(1)</script>")))
        val bytes = chapter.toString().toByteArray()
        Files.write(folder.resolve("chapters/0001.json"), bytes)
        val book = JSONObject().put("id", 4).put("title", "本の名前").put("cover_path", "cover.png")
            .put("chapters", JSONArray().put(JSONObject().put("id", 1).put("title", "第一章")
                .put("file", "chapters/0001.json").put("sha256", hash(bytes)).put("block_count", 1)))
        Files.writeString(folder.resolve("book.json"), JSONObject().put("version", 2).put("source_file", "original.epub")
            .put("source_sha256", hash(source)).put("book", book).put("resources", JSONObject()
                .put("cover.png", JSONObject().put("sha256", hash(byteArrayOf(1, 2, 3))))).toString())
        Files.writeString(folder.resolve("state.json"), """{"progress":{},"bookmarks":[],"revision":1}""")
        return folder
    }
    @Test fun syncedBookAppearsAndChapterIsReadableWithoutExecutingMarkup() {
        fixture()
        val api = LocalSyncedLibraryApi(data)
        val books = JSONObject(api.request("GET", "/api/books")!!.body).getJSONArray("books")
        assertEquals("本の名前", books.getJSONObject(0).getString("title"))
        val chapter = JSONObject(api.request("GET", "/api/books/4/chapters/1")!!.body).getJSONObject("chapter")
        assertEquals("本文です。", chapter.getJSONArray("blocks").getJSONObject(0).getString("text_ja"))
        assertFalse(chapter.getJSONArray("blocks").getJSONObject(0).getString("html").contains("script"))
        assertTrue(chapter.getJSONArray("blocks").getJSONObject(0).getString("html").contains("data-book-asset=\"cover.png\""))
        assertTrue(chapter.getJSONArray("blocks").getJSONObject(0).getString("html").contains("data-book-href=\"chapter.xhtml#next\""))
        assertArrayEquals(byteArrayOf(1, 2, 3), Files.readAllBytes(api.asset(4, "cover.png")))
        assertThrows(IllegalArgumentException::class.java) { api.asset(4, "../original.epub") }
    }
    @Test fun changedChapterAndMissingOriginalAreReported() {
        val folder = fixture()
        val api = LocalSyncedLibraryApi(data)
        Files.writeString(folder.resolve("chapters/0001.json"), "{}")
        assertEquals(409, api.request("GET", "/api/books/4/chapters/1")!!.status)
        Files.delete(folder.resolve("original.epub"))
        assertEquals(409, api.request("GET", "/api/books")!!.status)
    }
    @Test fun examplesShowTheirVerifiedOriginalText() {
        val folder = data.resolve("articles/examples/例文")
        Files.createDirectories(folder)
        val bytes = "今日は晴れ。".toByteArray()
        Files.write(folder.resolve("original.txt"), bytes)
        Files.writeString(folder.resolve("example.json"), JSONObject().put("id", "example-1").put("title", "例文")
            .put("text_sha256", hash(bytes)).toString())
        val api = LocalSyncedLibraryApi(data)
        assertEquals("今日は晴れ。", JSONArray(api.request("GET", "/api/examples")!!.body).getJSONObject(0).getString("text"))
        Files.writeString(folder.resolve("original.txt"), "changed")
        assertEquals(409, api.request("GET", "/api/examples")!!.status)
    }

    @Test fun selectedPcBrowserVoiceUsesMatchingChapterVersionWithoutFallingBack() {
        val folder = fixture()
        Files.createDirectories(folder.resolve("audio"))
        val first = "圭太_第一章.mp3"; val second = "春日部つむぎ_第一章.wav"
        Files.write(folder.resolve("audio/$first"), byteArrayOf(1, 2, 3))
        Files.write(folder.resolve("audio/$second"), byteArrayOf(4, 5, 6))
        val chapter = SyncFiles.json(folder.resolve("chapters/0001.json"))
        chapter.put("audio", JSONObject().put("path", first).put("voice_name", "ja-JP-KeitaNeural"))
        chapter.put("audio_versions", JSONArray().put(JSONObject().put("path", second).put("voice_name", "voicevox:8")))
        SyncFiles.writeJson(folder.resolve("chapters/0001.json"), chapter)
        val meta = SyncFiles.json(folder.resolve("book.json"))
        meta.getJSONObject("book").getJSONArray("chapters").getJSONObject(0).put("sha256", SyncFiles.hash(folder.resolve("chapters/0001.json")))
        meta.put("audio", JSONObject().put(first, JSONObject().put("sha256", hash(byteArrayOf(1, 2, 3))))
            .put(second, JSONObject().put("sha256", hash(byteArrayOf(4, 5, 6)))))
        SyncFiles.writeJson(folder.resolve("book.json"), meta)
        var selected = "voicevox:8"
        val voices = JSONArray().put(JSONObject().put("id", "voicevox:8").put("name", "春日部つむぎ").put("saved_audio_only", true))
            .put(JSONObject().put("id", "kokoro:jf_alpha").put("name", "アルファ").put("saved_audio_only", true))
        val api = LocalSyncedLibraryApi(data, { JSONObject().put("mode", "browser").put("browser_voice_name", selected) }, { voices })
        assertEquals(200, api.request("POST", "/api/books/4/chapters/1/reread", "{\"mode\":\"browser\",\"browser_voice_name\":\"voicevox:8\"}")!!.status)
        var result = JSONObject(api.request("GET", "/api/books/4/chapters/1")!!.body).getJSONObject("chapter")
        assertEquals("voicevox:8", result.getJSONObject("audio").getString("voice_name"))
        assertEquals("/api/books/4/audio/$second", java.net.URI(result.getJSONObject("audio").getString("url")).path)
        assertEquals(409, api.request("POST", "/api/books/4/chapters/1/reread", "{\"mode\":\"browser\",\"browser_voice_name\":\"kokoro:jf_alpha\"}")!!.status)
        assertEquals(200, api.request("POST", "/api/books/4/chapters/1/reread", "{\"mode\":\"browser\",\"browser_voice_name\":\"voicevox:8\"}")!!.status)
    }

    @Test fun registeredBookRecordingSurvivesDefaultEdgeAndEncodesSpecialCharacters() {
        val folder = fixture()
        val filename = "昔の声線_第#1章_100%録音.wav"
        Files.createDirectories(folder.resolve("audio"))
        Files.write(folder.resolve("audio/$filename"), byteArrayOf(1, 2, 3))
        val chapter = SyncFiles.json(folder.resolve("chapters/0001.json"))
        chapter.put("voice_mode", "voice").put("voice_id", 123)
            .put("audio", JSONObject().put("path", filename).put("voice_id", 123).put("status", "ready"))
        SyncFiles.writeJson(folder.resolve("chapters/0001.json"), chapter)
        val meta = SyncFiles.json(folder.resolve("book.json"))
        meta.getJSONObject("book").getJSONArray("chapters").getJSONObject(0).put("sha256", SyncFiles.hash(folder.resolve("chapters/0001.json")))
        meta.put("audio", JSONObject().put(filename, JSONObject().put("sha256", hash(byteArrayOf(1, 2, 3)))))
        SyncFiles.writeJson(folder.resolve("book.json"), meta)
        val api = LocalSyncedLibraryApi(data, { JSONObject().put("mode", "browser").put("browser_voice_name", "ja-JP-KeitaNeural") })
        val result = JSONObject(api.request("GET", "/api/books/4/chapters/1")!!.body).getJSONObject("chapter")
        assertEquals("ready", result.getJSONObject("audio").getString("status"))
        assertEquals("voice", result.getString("voice_mode"))
        assertEquals(123, result.getJSONObject("audio").getInt("voice_id"))
        val uri = java.net.URI(result.getJSONObject("audio").getString("url"))
        assertNull(uri.fragment)
        assertTrue(uri.rawPath.contains("%23") && uri.rawPath.contains("%25"))
        assertEquals("/api/books/4/audio/$filename", uri.path)
        assertEquals(200, api.request("POST", "/api/books/4/chapters/1/reread", "{\"mode\":\"voice\",\"voice_id\":123}")!!.status)
    }
}
