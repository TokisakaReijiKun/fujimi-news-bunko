package jp.fujimi.newsbunko.next.settings

import org.json.JSONArray
import org.json.JSONObject

/** The two online Japanese voices exposed by the Edge TTS service. */
object EdgeVoiceCatalog {
    const val KEITA = "ja-JP-KeitaNeural"
    const val NANAMI = "ja-JP-NanamiNeural"

    fun voices(): JSONArray = JSONArray().apply {
        put(voice(KEITA, "圭太"))
        put(voice(NANAMI, "七海"))
    }

    private fun voice(id: String, name: String) = JSONObject()
        .put("id", id)
        .put("name", name)
        .put("lang", "ja-JP")
        .put("provider", "edge-tts")
        .put("local", false)
        .put("available", true)
        .put("network_required", true)
        .put("default", id == KEITA)
}
