package jp.fujimi.newsbunko.next.store

import jp.fujimi.newsbunko.next.settings.EdgeVoiceCatalog
import jp.fujimi.newsbunko.next.settings.LocalSettingsApi
import jp.fujimi.newsbunko.next.settings.SettingsBackend
import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files
import java.nio.file.Path

class LocalVoiceStoreTest {
    @TempDir lateinit var root: Path
    @Test fun `catalog voice can be replaced by actual reference audio and selection follows it`() {
        val saved = mutableMapOf<String, String>()
        val backend = object : SettingsBackend {
            override fun read(key: String) = saved[key]
            override fun write(key: String, value: String) { saved[key] = value }
        }
        val file = Files.write(root.resolve("chosen.wav"), wav(7))
        val api = LocalSettingsApi(backend, referenceVoices = LocalVoiceStore(root)) { EdgeVoiceCatalog.voices() }
        val response = api.request("PUT", "/api/settings/browser-voices", """{"id":"ja-JP-KeitaNeural","name":"新しい声"}""", file)!!
        assertEquals(200, response.status)
        val id = LocalVoiceStore.id("新しい声")
        assertArrayEquals(wav(7), Files.readAllBytes(LocalVoiceStore(root).reference(id)))
        assertEquals("voice", api.value("voice-mode").getString("mode"))
        assertEquals(id, api.value("voice-mode").getLong("voice_id"))
        assertTrue((0 until api.browserVoices().length()).none { api.browserVoices().getJSONObject(it).getString("id") == "ja-JP-KeitaNeural" })
        val previous = saved.toMap()
        val invalid = Files.write(root.resolve("invalid.wav"), byteArrayOf(1, 2, 3))
        assertEquals(400, api.request("PUT", "/api/settings/browser-voices", """{"id":"ja-JP-NanamiNeural","name":"失敗"}""", invalid)!!.status)
        assertEquals(previous, saved)
        assertArrayEquals(wav(7), Files.readAllBytes(LocalVoiceStore(root).reference(id)))
    }

    @Test fun `system speech is available for unsaved article audio without a PC model`() {
        val article = ArticleStore(root).create(JSONObject().put("title", "新聞").put("url", "https://example.com/system")
            .put("paragraphs", JSONArray(listOf("本文。"))), "2026-11-08")
        val api = LocalLibraryApi(root, voiceSettings = { JSONObject().put("mode", "browser").put("browser_voice_name", "android:system") },
            browserVoices = { JSONArray().put(JSONObject().put("id", "android:system").put("name", "システム音声").put("available", true).put("saved_audio_only", false)) })
        val result = JSONObject(api.request("GET", "/api/articles/${article.metadata.getLong("id")}").body)
        assertEquals("browser", result.getString("audio_status"))
        assertFalse(result.has("audio_unavailable_detail"))
    }
    @Test fun `voice management renames without losing identity and deletes the selected file`() {
        val file = voice(root)
        val saved = mutableMapOf<String, String>()
        val backend = object : SettingsBackend {
            override fun read(key: String) = saved[key]
            override fun write(key: String, value: String) { saved[key] = value }
        }
        val api = LocalSettingsApi(backend, referenceVoices = LocalVoiceStore(root)) { EdgeVoiceCatalog.voices() }
        val id = LocalVoiceStore.id("テスト声線")
        api.request("PUT", "/api/settings/active-voice", "{\"voice_id\":$id}")
        assertEquals(200, api.request("PUT", "/api/settings/voices/$id", "{\"name\":\"改名后的声线\"}")!!.status)
        val row = JSONArray(api.request("GET", "/api/settings/voices", null)!!.body).getJSONObject(0)
        assertEquals("改名后的声线", row.getString("name"))
        assertEquals(id, row.getLong("id"))
        assertTrue(Files.exists(file))
        assertEquals(200, api.request("DELETE", "/api/settings/voices/$id", null)!!.status)
        assertFalse(Files.exists(file))
        assertEquals("none", api.value("voice-mode").getString("mode"))
    }
    private fun wav(seed: Byte = 0): ByteArray = ByteBuffer.allocate(44 + 32000).order(ByteOrder.LITTLE_ENDIAN).apply {
        put("RIFF".toByteArray()); putInt(32036); put("WAVEfmt ".toByteArray()); putInt(16)
        putShort(1); putShort(1); putInt(16000); putInt(32000); putShort(2); putShort(16)
        put("data".toByteArray()); putInt(32000); repeat(32000) { put(seed) }
    }.array()
    @Test fun `voice upload creates replaces and rejects invalid audio without changing saved bytes`() {
        val saved = mutableMapOf<String, String>()
        val api = LocalSettingsApi(object : SettingsBackend {
            override fun read(key: String) = saved[key]
            override fun write(key: String, value: String) { saved[key] = value }
        }, referenceVoices = LocalVoiceStore(root)) { EdgeVoiceCatalog.voices() }
        val input = Files.write(root.resolve("selected.wav"), wav(2))
        assertEquals(200, api.request("POST", "/api/settings/voices", "{\"name\":\"新增声线\"}", input)!!.status)
        val id = LocalVoiceStore.id("新增声线")
        val original = root.resolve("voices/新增声线.wav")
        Files.write(input, wav(3))
        assertEquals(200, api.request("PUT", "/api/settings/voices/$id", "{\"name\":\"显示名称\"}", input)!!.status)
        assertArrayEquals(wav(3), Files.readAllBytes(original))
        Files.write(input, byteArrayOf(1, 2, 3))
        assertEquals(400, api.request("PUT", "/api/settings/voices/$id", "{\"name\":\"无效替换\"}", input)!!.status)
        assertArrayEquals(wav(3), Files.readAllBytes(original))
        assertEquals("显示名称", JSONArray(api.request("GET", "/api/settings/voices", null)!!.body).getJSONObject(0).getString("name"))
        assertEquals(400, api.request("POST", "/api/settings/voices", "{\"name\":\"无文件\"}")!!.status)
    }
    private fun voice(folder: Path, name: String = "テスト声線", bytes: ByteArray = wav()): Path {
        Files.createDirectories(folder.resolve("voices"))
        return Files.write(folder.resolve("voices/$name.wav"), bytes)
    }

    @Test fun `reference resolves original validated bytes by stable ID without changing the file`() {
        val file = voice(root, bytes = wav(7))
        val before = Files.getLastModifiedTime(file)
        val store = LocalVoiceStore(root)
        assertEquals(file, store.reference(LocalVoiceStore.id("テスト声線")))
        assertArrayEquals(wav(7), Files.readAllBytes(store.reference(LocalVoiceStore.id("テスト声線"))))
        assertEquals(before, Files.getLastModifiedTime(file))
        assertThrows(NoSuchElementException::class.java) { store.reference(12) }
        Files.write(file, byteArrayOf(1, 2, 3))
        assertThrows(IllegalArgumentException::class.java) { store.reference(LocalVoiceStore.id("テスト声線")) }
    }

    @Test fun `voice bundle keeps original wav and same name equal size preserves local audio`() {
        val pc = root.resolve("pc"); val phone = root.resolve("phone")
        voice(pc)
        val store = LibrarySyncStore(pc)
        val item = store.manifest().getJSONArray("items").getJSONObject(0)
        assertEquals("voice", item.getString("kind"))
        assertEquals(LocalVoiceStore.key("テスト声線"), item.getString("key"))
        val zip = root.resolve("voice.zip")
        store.exportBundle(item.getString("key"), zip)
        assertEquals("created", LibrarySyncStore(phone).importBundle(zip).getString("status"))
        assertArrayEquals(wav(), Files.readAllBytes(phone.resolve("voices/テスト声線.wav")))
        assertEquals("unchanged", LibrarySyncStore(phone).importBundle(zip).getString("status"))
        voice(pc, bytes = wav(1)); store.exportBundle(item.getString("key"), zip)
        assertEquals("unchanged", LibrarySyncStore(phone).importBundle(zip).getString("status"))
        assertArrayEquals(wav(), Files.readAllBytes(phone.resolve("voices/テスト声線.wav")))
    }

    @Test fun `reference voice selection persists and does not replace browser choice`() {
        voice(root)
        val saved = mutableMapOf<String, String>()
        val backend = object : SettingsBackend {
            override fun read(key: String) = saved[key]
            override fun write(key: String, value: String) { saved[key] = value }
        }
        fun api() = LocalSettingsApi(backend, referenceVoices = LocalVoiceStore(root)) { EdgeVoiceCatalog.voices() }
        val id = LocalVoiceStore.id("テスト声線")
        assertEquals(200, api().request("PUT", "/api/settings/active-voice", "{\"voice_id\":$id}")!!.status)
        assertEquals("voice", api().value("voice-mode").getString("mode"))
        assertEquals("ja-JP-KeitaNeural", api().value("voice-mode").getString("browser_voice_name"))
        assertTrue(JSONArray(api().request("GET", "/api/settings/voices", null)!!.body).getJSONObject(0).getBoolean("active"))
        assertEquals(400, api().request("PUT", "/api/settings/active-voice", "{\"voice_id\":3}")!!.status)
        assertEquals(id, api().value("voice-mode").getLong("voice_id"))
    }

    @Test fun `selected reference voice chooses matching complete audio and never falls back to edge`() {
        voice(root)
        val article = ArticleStore(root).create(JSONObject().put("title", "新聞").put("url", "https://example.com/a")
            .put("paragraphs", JSONArray(listOf("本文。"))), "2026-10-17")
        val id = article.metadata.getLong("id")
        val selection = { JSONObject().put("mode", "voice").put("voice_id", LocalVoiceStore.id("テスト声線")) }
        val api = LocalLibraryApi(root, voiceSettings = selection)
        val missing = JSONObject(api.request("GET", "/api/articles/$id").body)
        assertEquals("unavailable", missing.getString("audio_status"))
        assertEquals("voice", missing.getString("audio_voice_mode"))
        assertTrue(missing.getString("audio_unavailable_detail").contains("PC"))
        Files.write(root.resolve(article.directory).resolve("audio/テスト声線_新聞-deadbeef.wav"), wav())
        val ready = JSONObject(api.request("GET", "/api/articles/$id").body)
        assertEquals("ready", ready.getString("audio_status"))
        assertEquals("テスト声線", ready.getString("audio_voice_name"))
        assertTrue(ready.getString("audio_path").endsWith("-deadbeef.wav"))
        assertEquals("ready", JSONObject(api.request("POST", "/api/articles/$id/reread", "{\"mode\":\"voice\",\"voice_id\":${LocalVoiceStore.id("テスト声線")}}").body).getString("status"))
    }

    @Test fun `PC browser voice catalog is selectable and audio comes from its saved name`() {
        val saved = mutableMapOf("pc-browser-voices" to "[{\"id\":\"voicevox:8\",\"name\":\"春日部つむぎ\",\"provider\":\"voicevox\",\"lang\":\"ja-JP\"}]")
        val backend = object : SettingsBackend {
            override fun read(key: String) = saved[key]
            override fun write(key: String, value: String) { saved[key] = value }
        }
        val api = LocalSettingsApi(backend) { EdgeVoiceCatalog.voices() }
        val catalog = JSONArray(api.request("GET", "/api/browser-voices", null)!!.body)
        assertEquals(3, catalog.length())
        assertTrue(catalog.getJSONObject(2).getBoolean("saved_audio_only"))
        assertEquals(200, api.request("PUT", "/api/settings/browser-voice", "{\"name\":\"voicevox:8\",\"label\":\"春日部つむぎ\"}")!!.status)
        val item = ArticleStore(root).create(JSONObject().put("title", "新聞").put("url", "https://example.com/a")
            .put("paragraphs", JSONArray(listOf("本文。"))), "2026-10-17")
        Files.write(root.resolve(item.directory).resolve("audio/春日部つむぎ_新聞.wav"), wav())
        val library = LocalLibraryApi(root, voiceSettings = { api.value("voice-mode") }, browserVoices = { catalog })
        val article = JSONObject(library.request("GET", "/api/articles/${item.metadata.getLong("id")}").body)
        assertEquals("ready", article.getString("audio_status"))
        assertEquals("voicevox:8", article.getString("audio_voice_name"))
    }

    @Test fun `invalid reference files do not become voices`() {
        voice(root, "偽装", byteArrayOf(1, 2, 3))
        assertEquals(0, LocalVoiceStore(root).list().length())
        assertEquals(1, LibrarySyncStore(root).manifest().getJSONArray("errors").length())
    }

    @Test fun `explicit Edge reread cannot reuse another voice audio`() {
        val item = ArticleStore(root).create(JSONObject().put("title", "新聞").put("url", "https://example.com/a")
            .put("paragraphs", JSONArray(listOf("本文。"))), "2026-10-17")
        Files.write(root.resolve(item.directory).resolve("audio/別声線_新聞.wav"), wav())
        val manifest = SyncFiles.json(root.resolve(item.directory).resolve("article.json"))
        manifest.getJSONObject("article").put("audio_path", "audio/別声線_新聞.wav")
            .put("audio_voice_mode", "voice").put("audio_voice_id", 8).put("audio_status", "ready")
        SyncFiles.writeJson(root.resolve(item.directory).resolve("article.json"), manifest)
        val library = LocalLibraryApi(root, voiceSettings = { JSONObject().put("mode", "browser").put("browser_voice_name", "ja-JP-KeitaNeural") }, browserVoices = EdgeVoiceCatalog::voices)
        val path = "/api/articles/${item.metadata.getLong("id")}"
        assertEquals(409, library.request("POST", "$path/reread", "{\"mode\":\"browser\",\"browser_voice_name\":\"ja-JP-KeitaNeural\"}").status)
        Files.write(root.resolve(item.directory).resolve("audio/圭太_新聞.mp3"), byteArrayOf(1, 2, 3))
        val article = JSONObject(library.request("POST", "$path/reread", "{\"mode\":\"browser\",\"browser_voice_name\":\"ja-JP-KeitaNeural\"}").body).getJSONObject("article")
        assertEquals("ready", article.getString("audio_status"))
        assertEquals("ja-JP-KeitaNeural", article.getString("audio_voice_name"))
        assertTrue(article.getString("audio_path").endsWith(".mp3"))
    }

    @Test fun `explicit Edge reread returns that saved voice without changing global custom selection`() {
        voice(root)
        val selection = JSONObject().put("mode", "voice").put("voice_id", LocalVoiceStore.id("テスト声線"))
        val item = ArticleStore(root).create(JSONObject().put("title", "新聞").put("url", "https://example.com/a")
            .put("paragraphs", JSONArray(listOf("本文。"))), "2026-10-17")
        Files.write(root.resolve(item.directory).resolve("audio/圭太_新聞.mp3"), byteArrayOf(1, 2, 3))
        val api = LocalLibraryApi(root, voiceSettings = { selection }, browserVoices = EdgeVoiceCatalog::voices)
        val route = "/api/articles/${item.metadata.getLong("id")}"
        val result = api.request("POST", "$route/reread", "{\"mode\":\"browser\",\"browser_voice_name\":\"ja-JP-KeitaNeural\"}")
        assertEquals(200, result.status)
        val article = JSONObject(result.body).getJSONObject("article")
        assertEquals("ready", article.getString("audio_status"))
        assertEquals("ja-JP-KeitaNeural", article.getString("audio_voice_name"))
        assertTrue(article.getString("audio_path").endsWith(".mp3"))
        val global = JSONObject(api.request("GET", route).body)
        assertEquals("voice", global.getString("audio_voice_mode"))
        assertEquals("unavailable", global.getString("audio_status"))
        assertEquals("voice", selection.getString("mode"))
    }

    @Test fun `registered PC recording survives default Edge and renamed title with stable voice id`() {
        voice(root)
        val selectedId = LocalVoiceStore.id("テスト声線")
        val item = ArticleStore(root).create(JSONObject().put("title", "変更後のタイトル").put("url", "https://example.com/old")
            .put("paragraphs", JSONArray(listOf("本文。"))), "2026-10-17")
        val filename = "テスト声線_旧タイトルの長い名前を変更せずに保存した既存の録音ファイル.wav"
        Files.write(root.resolve(item.directory).resolve("audio/$filename"), wav())
        val manifest = SyncFiles.json(root.resolve(item.directory).resolve("article.json"))
        manifest.getJSONObject("article").put("audio_path", "audio/$filename").put("audio_status", "ready")
            .put("audio_voice_mode", "voice").put("audio_voice_id", selectedId).put("audio_voice_name", JSONObject.NULL)
        SyncFiles.writeJson(root.resolve(item.directory).resolve("article.json"), manifest)
        val api = LocalLibraryApi(root, voiceSettings = { JSONObject().put("mode", "browser").put("browser_voice_name", "ja-JP-KeitaNeural") }, browserVoices = EdgeVoiceCatalog::voices)
        val route = "/api/articles/${item.metadata.getLong("id")}"
        val current = JSONObject(api.request("GET", route).body)
        assertEquals("ready", current.getString("audio_status"))
        assertEquals("voice", current.getString("audio_voice_mode"))
        assertEquals(selectedId, current.getLong("audio_voice_id"))
        assertEquals("テスト声線", current.getString("audio_voice_name"))
        assertFalse(current.has("audio_unavailable_detail"))
        val reread = api.request("POST", "$route/reread", "{\"mode\":\"voice\",\"voice_id\":$selectedId}")
        assertEquals(200, reread.status)
        assertEquals("ready", JSONObject(reread.body).getJSONObject("article").getString("audio_status"))
    }
}
