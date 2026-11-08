package jp.fujimi.newsbunko.next.store

import jp.fujimi.newsbunko.next.dictionary.MojiOfflineSearch
import org.junit.jupiter.api.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class MojiOfflineSearchTest {
    @Test fun `retains original kana and simplified to traditional query variants`() {
        assertEquals(1, MojiOfflineSearch.queryType("かいちょう"))
        assertEquals(2, MojiOfflineSearch.queryType("ニュース"))
        assertEquals(3, MojiOfflineSearch.queryType("会長"))
        assertEquals(4, MojiOfflineSearch.queryType("食べた"))
        assertTrue(MojiOfflineSearch.queries("会長").any { it.model == "Wort" && it.field == "spell" && it.operation == "EQUAL" && it.value == "會長" && it.score == 990 })
        assertTrue(MojiOfflineSearch.queries("ニュース").any { it.field == "pron" && it.value == "にゅーす" && it.operation == "EQUAL" })
        assertTrue(MojiOfflineSearch.queries("かいちょう").any { it.field == "spell" && it.value == "カイチョウ" })
    }

    @Test fun `original shortened pronunciation queries can find an inflected surface`() {
        val seen = ArrayList<MojiOfflineSearch.Query>()
        val found = MojiOfflineSearch.search("たべました") { query, limit ->
            seen += query
            assertEquals(30, limit)
            if (query.model == "Wort" && query.field == "pron" && query.operation == "LIKE" && query.value == "たべ*")
                listOf(MojiOfflineSearch.Row("word-eat", "Wort", "word-eat", "食べる")) else emptyList()
        }
        assertEquals("word-eat", assertNotNull(found).row.pk)
        assertEquals(499, found.score)
        assertEquals(listOf(699, 599, 499), seen.filter { it.score < 700 }.map { it.score })
    }

    @Test fun `query scores and row deductions preserve the original selection order`() {
        val found = MojiOfflineSearch.search("会長") { query, _ ->
            when {
                query.model == "Subdetails" && query.value == "*会長*" -> listOf(MojiOfflineSearch.Row("sense-1", "Subdetails", "other-word", "別語"))
                query.model == "Wort" && query.value == "*会長*" -> listOf(
                    MojiOfflineSearch.Row("word-1", "Wort", "word-1", "会長"),
                    MojiOfflineSearch.Row("word-2", "Wort", "word-2", "副会長"),
                )
                else -> emptyList()
            }
        }
        assertEquals("word-1", assertNotNull(found).row.pk)
        assertEquals(800, found.score)
        // Original marks each model pk on its first hit. Later exact/prefix hits do not rescore it.
    }

    @Test fun `matching remains case sensitive and neither lowercases nor changes per query limit`() {
        val store = { query: MojiOfflineSearch.Query, limit: Int ->
            assertEquals(30, limit)
            assertFalse(query.ignoreCase)
            val matches = query.model == "Wort" && query.field == "spell" && when (query.operation) {
                "EQUAL" -> query.value == "abc"
                "LIKE" -> Regex("^" + query.value.map { char -> when (char) { '*' -> ".*"; '?' -> "."; else -> Regex.escape(char.toString()) } }.joinToString("") + "$").matches("abc")
                else -> false
            }
            if (matches) listOf(MojiOfflineSearch.Row("lower", "Wort", "lower", "abc")) else emptyList()
        }
        assertNull(MojiOfflineSearch.search("ABC", store))
        assertEquals("lower", assertNotNull(MojiOfflineSearch.search("abc", store)).row.pk)
    }

    @Test fun `retains original sixty one candidate boundary and thirty rows per clause`() {
        var queryCount = 0
        val found = MojiOfflineSearch.searchSources("abc", 1) { source, query, limit ->
            assertEquals(0, source)
            assertEquals(30, limit)
            val batch = queryCount++
            List(limit) { row -> MojiOfflineSearch.Row("$batch-$row", query.model, "$batch-$row", "word", ordinal = row.toLong()) }
        }
        assertEquals(61, found.size)
        assertEquals(3, queryCount)
        assertEquals(1000, found.maxOf { it.score })
    }
}
