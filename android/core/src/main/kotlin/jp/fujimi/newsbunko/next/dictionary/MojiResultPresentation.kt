package jp.fujimi.newsbunko.next.dictionary

import org.json.JSONArray
import org.json.JSONObject

/**
 * Literal result-presentation translation from the supplied MOJi APK.
 * Evidence: ArticleWordExpandView.smali s.g, WordExpandBase.smali e.a/b/f,
 * WortEntity.smali formalTitle/titleWithDisplayType(0), WordModelHelpers.smali
 * aj.h.h, ResultTextCleanup.smali e9.c.b, WordCardPartOfSpeech.smali lb.s0.
 *
 * Database access, Realm-listener replacement and native widget bindings are
 * supplied by the Android adapter; this object preserves presentation rules.
 */
object MojiResultPresentation {
    /**
     * [result] has the original WordClickSearchResult shape: word/details/subdetails.
     * [localWord] is the existing local Wort with the same pk, used only by e.a.
     * Original WordConfigEntity() uses katuyouType = 0.
     * A null [simpToTrad] matches e9.c.a's simplified-Chinese/default path.
     * Return null means s.g invokes the original empty-result handler s.e.
     */
    fun present(
        result: JSONObject,
        katuyouType: Int = 0,
        localWord: JSONObject? = null,
        simpToTrad: JSONObject? = null,
    ): JSONObject? {
        val word = result.getJSONObject("word")
        val details = result.getJSONArray("details")
        val subdetails = result.getJSONArray("subdetails")
        val firstDetail = details.optJSONObject(0) ?: return null
        val firstSubdetail = subdetails.optJSONObject(0) ?: return null

        // s.g first asks aj.h.h(word); only an empty result invokes e.a(local Wort).
        val summary = excerpt(word, katuyouType)
        val localSummary = if (summary.isEmpty() && localWord != null) excerpt(localWord, katuyouType) else ""
        val part = partOfSpeech(if (summary.isEmpty()) localSummary else summary)
        val speechIds = firstDetail.optJSONArray("partOfSpeech")
        val firstSpeechId = if (speechIds != null && speechIds.length() != 0) speechIds.getInt(0) else null
        val libId = string(firstSubdetail, "libId")
        val wordId = string(word, "objectId")

        return JSONObject()
            .put("title", formalTitle(word))
            .put("partOfSpeech", part)
            .put("partOfSpeechVisible", part.isNotEmpty())
            .put("partOfSpeechColor", if (part.isNotEmpty()) POS_COLORS[firstSpeechId] ?: 0 else JSONObject.NULL)
            .put("meaning", convertMeaning(joinMeanings(subdetails), simpToTrad))
            // db.c.e builds mc.f(targetType=102, targetId=Wort.pk, title=Wort.spell).
            // The title is not proof of an equivalent TTS pronunciation strategy.
            .put("speechText", string(word, "spell"))
            .put("speechTargetType", 102)
            .put("speechTargetId", wordId)
            .put("favoriteTargetType", 102)
            .put("favoriteTargetId", wordId)
            .put("showFavorite", libId.isEmpty())
            .put("showDictionaryPanelBackground", libId.isNotEmpty())
            // e.a adds a Realm listener and requests ma.j.a(pk) only in this case.
            .put("excerptHydrationRequested", summary.isEmpty() && localWord != null && localSummary.isEmpty())
    }

    /** Wort.formalTitle -> titleWithDisplayType(0), including exact spaces. */
    fun formalTitle(word: JSONObject): String {
        val spell = string(word, "spell")
        val pron = string(word, "pron")
        val accent = string(word, "accent")
        val title = StringBuilder(spell)
        if (pron.isNotEmpty() && spell != pron) {
            if (spell.isNotEmpty()) title.append(" | ")
            title.append(pron)
        }
        if (accent.isNotEmpty()) title.append(' ').append(accent)
        return title.toString()
    }

    /** aj.h.h: null excerptB falls back to excerpt; an empty excerptB does not. */
    fun excerpt(word: JSONObject, katuyouType: Int): String =
        if (katuyouType == 2 && !word.isNull("excerptB")) word.getString("excerptB") else string(word, "excerpt")

    /** e.b checks ']' only, then uses the first '[' index plus one verbatim. */
    fun partOfSpeech(summary: String): String =
        if (summary.contains(']')) summary.substring(summary.indexOf('[') + 1, summary.indexOf(']')) else ""

    /** s.g groups by relaId in encounter order, uses first zh-CN and first ja. */
    fun joinMeanings(subdetails: JSONArray): String {
        val groups = linkedMapOf<String?, MutableList<JSONObject>>()
        for (index in 0 until subdetails.length()) {
            val sub = subdetails.getJSONObject(index)
            val id = if (sub.isNull("relaId")) null else sub.getString("relaId")
            groups.getOrPut(id) { mutableListOf() }.add(sub)
        }
        val text = StringBuilder()
        for (group in groups.values) {
            val zh = group.firstOrNull { string(it, "lang") == "zh-CN" }?.let { string(it, "title") } ?: ""
            val ja = group.firstOrNull { string(it, "lang") == "ja" }?.let { string(it, "title") } ?: ""
            text.append(zh)
            if (ja.isNotEmpty()) text.append('(').append(ja).append(')')
            text.append("\n\n")
        }
        return text.toString()
    }

    /** e9.c.b; original simp2trad.json mapping is supplied only for traditional UI. */
    fun convertMeaning(text: String, simpToTrad: JSONObject?): String {
        if (text.isEmpty() || simpToTrad == null) return text
        val keys = simpToTrad.keys().asSequence().toList()
        if (text.none { it.toString() in keys }) return text
        val reverseKeys = keys.map { simpToTrad.getString(it) }.toSet()
        val output = StringBuilder()
        for (index in text.indices) {
            val character = text[index]
            val replacement = simpToTrad.optString(character.toString()).takeIf { it.isNotEmpty() }
            var useReplacement = replacement != null
            if (replacement != null && charType(replacement[0]) == 2) {
                for (near in maxOf(0, index - 4) until minOf(index + 5, text.length)) {
                    val adjacent = text[near]
                    if (charType(adjacent) == 1 || charType(adjacent) == 0 || adjacent.toString() in reverseKeys) {
                        useReplacement = false
                        break
                    }
                }
            }
            if (useReplacement) output.append(replacement) else output.append(character)
        }
        return output.toString()
    }

    private fun charType(character: Char): Int = when (character.code) {
        in 0x3040..0x309f -> 0
        in 0x30a0..0x30ff -> 1
        in 0x4e00..0x9fff -> 2
        else -> 99
    }

    private fun string(value: JSONObject, key: String): String = if (value.isNull(key)) "" else value.getString(key)

    // lb.s0 enum's original partOfSpeech ID -> raw signed ARGB color.
    private val POS_COLORS = mapOf(
        1 to -16722697, 2 to -16722697, 3 to -1004112, 4 to -22207,
        5 to -7889316, 6 to -15482174, 7 to -22207, 8 to -2501385,
        9 to -1004112, 10 to -22207, 11 to -22207, 12 to -15482174,
        13 to -15482174, 14 to -3210417, 15 to -1004112, 16 to -1004112,
        17 to -1004112, 18 to -1004112, 19 to -22207,
    )
}
