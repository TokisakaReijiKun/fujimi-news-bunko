package jp.fujimi.newsbunko.next.store

import jp.fujimi.newsbunko.next.dictionary.MojiLookupTokenizer
import org.junit.jupiter.api.Test
import kotlin.test.assertEquals

class MojiLookupTokenizerTest {
    @Test fun `uses the original ipadic surface boundaries including inflections`() {
        assertEquals(listOf("日本", "で", "ニュース", "を", "読み", "ます", "。"), MojiLookupTokenizer.surfaces("日本でニュースを読みます。"))
        assertEquals(listOf("開催", "国"), MojiLookupTokenizer.surfaces("開催国"))
        assertEquals(listOf("遅い", "電車", "です", "。"), MojiLookupTokenizer.surfaces("遅い電車です。"))
        val input = "東京へ行きます。\n A & B";
        assertEquals(input, MojiLookupTokenizer.surfaces(input).joinToString(""))
    }
}
