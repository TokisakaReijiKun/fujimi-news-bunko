package jp.fujimi.newsbunko.next.store

import jp.fujimi.newsbunko.next.dictionary.MojiLocalDictionaryAdapter
import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class MojiLocalDictionaryAdapterTest {
    @Test fun `keeps local data and builds only the explicit definition relations`() {
        val definitions = JSONArray()
            .put(definition("ja-one", "group-b", "ja", " 日本語 "))
            .put(definition("zh-one", "group-a", "zh-CN", " 先にある訳 "))
            .put(definition("zh-two", "group-b", "zh-CN", " 後にある訳 "))
        val local = local(definitions).put("id", 42).put("custom", JSONObject().put("unchanged", true))
        val before = local.toString()
        val response = MojiLocalDictionaryAdapter.response(local)
        assertEquals(before, local.toString(), "The adapter must not modify the local entry")
        for (key in local.keySet()) assertEquals(local.get(key).toString(), response.get(key).toString(), key)
        assertEquals(42, response.getInt("id"))

        val result = response.getJSONObject("moji_result")
        assertEquals("42", result.getJSONObject("word").getString("objectId"))
        assertEquals("kaichou", result.getJSONObject("word").getString("romaji_hepburn_CN"))
        val groups = result.getJSONArray("details")
        assertEquals(2, groups.length())
        assertEquals("group-b", groups.getJSONObject(0).getString("objectId"))
        assertEquals("group-a", groups.getJSONObject(1).getString("objectId"))
        assertEquals("42", groups.getJSONObject(0).getString("wordId"))
        assertEquals(0, groups.getJSONObject(0).getJSONArray("partOfSpeech").length())
        assertEquals(setOf("objectId", "wordId", "partOfSpeech"), groups.getJSONObject(0).keySet())

        val subs = result.getJSONArray("subdetails")
        assertEquals(listOf("ja-one", "zh-one", "zh-two"), (0 until subs.length()).map { subs.getJSONObject(it).getString("id") })
        assertEquals("group-b", subs.getJSONObject(0).getString("relaId"))
        assertEquals(" 日本語 ", subs.getJSONObject(0).getString("title"))
        assertEquals(" 後にある訳 ( 日本語 )\n\n 先にある訳 \n\n", response.getJSONObject("moji_card").getString("meaning"))
    }

    @Test fun `existing details are copied without generated or rewritten groups`() {
        val details = JSONArray().put(JSONObject().put("objectId", "original-detail").put("wordId", "7")
            .put("partOfSpeech", JSONArray().put(1)).put("preserved", " 原字段 "))
        val local = local(JSONArray().put(definition("sense", "definition-group", "zh-CN", " 原释义 ")))
            .put("details", details)
        val response = MojiLocalDictionaryAdapter.response(local)
        assertTrue(details.similar(response.getJSONObject("moji_result").getJSONArray("details")))
        assertEquals(1, response.getJSONObject("moji_result").getJSONArray("details").length())
        assertEquals(" 原释义 \n\n", response.getJSONObject("moji_card").getString("meaning"))
        assertFalse(local.has("moji_result"))
    }

    @Test fun `does not invent a relation or card when definitions have no detailsId`() {
        val definitions = JSONArray().put(JSONObject().put("id", "sense-without-relation").put("lang", "zh-CN").put("title", "原文"))
        val response = MojiLocalDictionaryAdapter.response(local(definitions))
        val result = response.getJSONObject("moji_result")
        assertEquals(0, result.getJSONArray("details").length())
        assertFalse(result.getJSONArray("subdetails").getJSONObject(0).has("relaId"))
        assertTrue(response.isNull("moji_card"))
        assertEquals("原文", response.getJSONArray("definitions").getJSONObject(0).getString("title"))
    }

    private fun definition(id: String, detailsId: String, lang: String, title: String) = JSONObject()
        .put("id", id).put("detailsId", detailsId).put("lang", lang).put("title", title)

    private fun local(definitions: JSONArray) = JSONObject().put("id", "7").put("spell", "会長").put("pron", "かいちょう")
        .put("accent", "⓪").put("romaji", "kaichou").put("excerpt", "[名]会长")
        .put("definitions", definitions).put("details", JSONArray()).put("examples", JSONArray()).put("sections", JSONArray())
}
