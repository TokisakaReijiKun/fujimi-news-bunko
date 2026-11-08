package jp.fujimi.newsbunko.next.store

import jp.fujimi.newsbunko.next.dictionary.MojiResultPresentation
import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class MojiResultPresentationTest {
    @Test fun `formal title keeps original accents and spaces`() {
        val word = JSONObject().put("spell", "会長").put("pron", "かいちょう").put("accent", "⓪")
        assertEquals("会長 | かいちょう ⓪", MojiResultPresentation.formalTitle(word))
        word.put("spell", "ニュース").put("pron", "ニュース").put("accent", "0")
        assertEquals("ニュース 0", MojiResultPresentation.formalTitle(word))
        word.put("spell", "").put("pron", "かいちょう").put("accent", "①②")
        assertEquals("かいちょう ①②", MojiResultPresentation.formalTitle(word))
    }

    @Test fun `part of speech is the original bracket text`() {
        assertEquals(" 名・自五 ", MojiResultPresentation.partOfSpeech(" [ 名・自五 ]説明"))
        assertEquals("", MojiResultPresentation.partOfSpeech("説明だけ"))
        assertEquals("先頭", MojiResultPresentation.partOfSpeech("先頭]説明"))
        val word = JSONObject().put("excerpt", "[名]普通").put("excerptB", "")
        assertEquals("", MojiResultPresentation.excerpt(word, 2), "An empty excerptB is not a missing field")
        word.put("excerptB", JSONObject.NULL)
        assertEquals("[名]普通", MojiResultPresentation.excerpt(word, 2))
    }

    @Test fun `meaning keeps group encounter order first language ASCII brackets and trailing blank line`() {
        val subdetails = JSONArray()
            .put(sub("b", "ja", " 日本語 "))
            .put(sub("a", "zh-CN", " 第二组 "))
            .put(sub("b", "zh-CN", " 第一组 "))
            .put(sub("b", "zh-CN", "同语言后续释义不拼入词卡"))
            .put(sub("b", "ja", "同语言后续日文不拼入词卡"))
        assertEquals(" 第一组 ( 日本語 )\n\n 第二组 \n\n", MojiResultPresentation.joinMeanings(subdetails))
        val result = result(subdetails)
        val card = MojiResultPresentation.present(result)!!
        assertEquals(" 名 ", card.getString("partOfSpeech"))
        assertEquals(-16722697, card.getInt("partOfSpeechColor"))
        assertEquals("会長", card.getString("speechText"))
        assertEquals("word-id", card.getString("speechTargetId"))
    }

    @Test fun `empty original details or subdetails use the empty result branch`() {
        val result = result(JSONArray().put(sub("a", "zh-CN", "释义")))
        result.put("details", JSONArray())
        assertNull(MojiResultPresentation.present(result))
        result.put("details", JSONArray().put(JSONObject()))
        result.put("subdetails", JSONArray())
        assertNull(MojiResultPresentation.present(result))
    }

    private fun sub(relaId: String, lang: String, title: String): JSONObject =
        JSONObject().put("relaId", relaId).put("lang", lang).put("title", title)

    private fun result(subdetails: JSONArray): JSONObject = JSONObject()
        .put("word", JSONObject().put("objectId", "word-id").put("spell", "会長").put("pron", "かいちょう").put("excerpt", "[ 名 ]释义"))
        .put("details", JSONArray().put(JSONObject().put("partOfSpeech", JSONArray().put(1))))
        .put("subdetails", subdetails)
}
