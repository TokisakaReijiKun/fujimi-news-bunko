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
    @Test fun `system speech stays visible and cannot be renamed or hidden`() {
        val system = JSONObject().put("id", "android:system").put("name", "システム音声")
            .put("available", true).put("read_only", true)
        data["voice-customizations"] = """{"browser":{"android:system":{"name":"wrong","hidden":true}}}"""
        val api = LocalSettingsApi(backend) { JSONArray().put(system) }
        val rows = api.browserVoices()
        assertEquals(1, rows.length())
        assertEquals("システム音声", rows.getJSONObject(0).getString("name"))
        val before = data.toMap()
        assertEquals(400, api.request("DELETE", "/api/settings/browser-voices", """{"id":"android:system"}""")!!.status)
        assertEquals(400, api.request("PUT", "/api/settings/browser-voices", """{"id":"android:system","name":"wrong"}""")!!.status)
        assertEquals(before, data)
        assertEquals(200, api.request("PUT", "/api/settings/browser-voice", """{"name":"android:system","label":"システム音声"}""")!!.status)
        assertEquals("android:system", api.value("voice-mode").getString("browser_voice_name"))
    }
    @Test fun `voice management edits removes and restores catalog choices with stable IDs`() {
        val api = api()
        val body = """{"id":"ja-JP-KeitaNeural","name":"我的声线"}"""
        assertEquals(200, api.request("PUT", "/api/settings/browser-voices", body)!!.status)
        var list = JSONArray(api.request("GET", "/api/browser-voices", null)!!.body)
        assertEquals("我的声线", list.getJSONObject(0).getString("name"))
        assertEquals(200, api.request("DELETE", "/api/settings/browser-voices", body)!!.status)
        list = JSONArray(api.request("GET", "/api/browser-voices", null)!!.body)
        assertTrue((0 until list.length()).none { list.getJSONObject(it).getString("id") == "ja-JP-KeitaNeural" })
        assertEquals("none", api.value("voice-mode").getString("mode"))
        assertEquals(200, api.request("POST", "/api/settings/browser-voices", body)!!.status)
        assertEquals(2, JSONArray(api.request("GET", "/api/browser-voices", null)!!.body).length())
    }

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

    @Test fun `source quotas and daily target enforce the same total without changing rejected settings`() {
        val api = api()
        assertEquals(200, api.request("PUT", "/api/settings/news-sources/1", "{\"minimum_count\":5}")!!.status)
        val saved = data.toMap()
        assertEquals(400, api.request("PUT", "/api/settings/news-sources/2", "{\"minimum_count\":2}")!!.status)
        assertEquals(400, api.request("PUT", "/api/settings/daily-content", "{\"target_count\":9}")!!.status)
        assertEquals(saved, data)
        assertEquals(200, api.request("PUT", "/api/settings/news-sources/1", "{\"minimum_count\":4}")!!.status)
        assertEquals(200, api.request("PUT", "/api/settings/news-sources/2", "{\"minimum_count\":2}")!!.status)
        assertEquals(200, api.request("PUT", "/api/settings/daily-content", "{\"target_count\":10}")!!.status)
    }

    @Test fun `new source cannot consume more than the remaining article count`() {
        val api = api()
        val source = """{"name":"New source","homepage":"https://example.com/","minimum_count":5,"voice_mode":"inherit"}"""
        assertEquals(400, api.request("POST", "/api/settings/news-sources", source)!!.status)
        assertTrue(data.isEmpty())
        assertEquals(200, api.request("POST", "/api/settings/news-sources", source.replace(":5", ":4"))!!.status)
        assertEquals(10, JSONObject(api.request("GET", "/api/settings/daily-content", null)!!.body).getInt("required_count"))
    }
}
