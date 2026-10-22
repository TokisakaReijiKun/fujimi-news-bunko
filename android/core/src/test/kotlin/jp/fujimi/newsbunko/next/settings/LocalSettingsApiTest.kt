package jp.fujimi.newsbunko.next.settings

import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class LocalSettingsApiTest {
    private val data = mutableMapOf<String, String>()
    private val backend = object : SettingsBackend {
        override fun read(key: String) = data[key]
        override fun write(key: String, value: String) { data[key] = value }
    }
    private fun api() = LocalSettingsApi(backend) { EdgeVoiceCatalog.voices() }

    @Test fun `settings survive a new API instance without changing content paths`() {
        assertEquals(200, api().request("PUT", "/api/settings/library", "{\"sort\":\"series\",\"lookup_chinese_translations\":false}")!!.status)
        assertEquals("series", JSONObject(api().request("GET", "/api/settings/library", null)!!.body).getString("sort"))
        assertEquals(setOf("library"), data.keys)
    }

    @Test fun `invalid edits and unavailable schedules do not overwrite saved settings`() {
        assertEquals(400, api().request("PUT", "/api/settings/daily-content", "{\"target_count\":1.5}")!!.status)
        assertEquals(400, api().request("PUT", "/api/settings/library", "{\"lookup_chinese_translations\":\"false\"}")!!.status)
        assertEquals(501, api().request("PUT", "/api/settings/daily-schedule", "{\"mode\":\"automatic\",\"time\":\"09:00\"}")!!.status)
        assertTrue(data.isEmpty())
    }

    @Test fun `selecting an unavailable voice preserves the actual selected voice`() {
        assertEquals(200, api().request("PUT", "/api/settings/browser-voice", "{\"name\":\"ja-JP-NanamiNeural\",\"label\":\"七海\"}")!!.status)
        assertEquals(400, api().request("PUT", "/api/settings/browser-voice", "{\"name\":\"missing\"}")!!.status)
        assertEquals("ja-JP-NanamiNeural", api().value("voice-mode").getString("browser_voice_name"))
    }

    @Test fun `source settings preserve IDs and recalculate quotas`() {
        assertEquals(200, api().request("PUT", "/api/settings/news-sources/1", "{\"minimum_count\":3}")!!.status)
        val content = JSONObject(api().request("GET", "/api/settings/daily-content", null)!!.body)
        assertEquals(8, content.getInt("required_count"))
        assertEquals(6, content.getInt("source_count"))
        assertEquals(400, api().request("PUT", "/api/settings/news-sources/1", "{\"minimum_count\":-1}")!!.status)
        assertEquals(3, JSONArray(api().request("GET", "/api/settings/news-sources", null)!!.body).getJSONObject(0).getInt("minimum_count"))
    }

    @Test fun `PC endpoint accepts HTTP and HTTPS only on private addresses`() {
        assertEquals("https://192.168.1.20:8429", PcEndpoint.normalize(" https://192.168.1.20:8429/ "))
        assertEquals("http://192.168.1.20:8429", PcEndpoint.normalize("http://192.168.1.20:8429/"))
        for (url in listOf("http://8.8.8.8", "http://127.0.0.1", "https://8.8.8.8", "https://192.168.1.20/api", "https://name:secret@192.168.1.20", "https://192.168.1.20?x=1", "https://172.32.0.1", "https://192.168.1.20:0")) {
            assertThrows(IllegalArgumentException::class.java) { PcEndpoint.normalize(url) }
        }
    }
}
