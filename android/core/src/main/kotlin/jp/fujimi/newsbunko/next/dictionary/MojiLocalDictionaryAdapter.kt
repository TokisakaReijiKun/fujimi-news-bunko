package jp.fujimi.newsbunko.next.dictionary

import org.json.JSONArray
import org.json.JSONObject

/** Adapts the existing dictionary schema to the original MOJi result presenter. */
object MojiLocalDictionaryAdapter {
    fun response(local: JSONObject): JSONObject {
        val response = JSONObject(local.toString())
        val word = JSONObject(local.toString())
        val wordId = local.get("id").toString()
        word.put("objectId", wordId)
        word.put("romaji_hepburn_CN", local.opt("romaji") ?: JSONObject.NULL)

        val details = JSONArray(local.getJSONArray("details").toString())
        val definitions = local.getJSONArray("definitions")
        val subdetails = JSONArray()
        val explicitGroups = linkedSetOf<String>()
        for (index in 0 until definitions.length()) {
            val original = definitions.getJSONObject(index)
            val sub = JSONObject(original.toString())
            if (!original.isNull("detailsId")) {
                val detailsId = original.get("detailsId").toString()
                sub.put("relaId", detailsId)
                if (detailsId.isNotEmpty()) explicitGroups.add(detailsId)
            }
            subdetails.put(sub)
        }
        if (details.length() == 0) {
            for (id in explicitGroups) {
                details.put(JSONObject().put("objectId", id).put("wordId", wordId).put("partOfSpeech", JSONArray()))
            }
        }

        val result = JSONObject().put("word", word).put("details", details).put("subdetails", subdetails)
        response.put("moji_result", result)
        response.put("moji_card", MojiResultPresentation.present(result) ?: JSONObject.NULL)
        return response
    }
}
