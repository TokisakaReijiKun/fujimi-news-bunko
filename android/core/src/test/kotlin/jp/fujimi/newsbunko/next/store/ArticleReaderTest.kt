package jp.fujimi.newsbunko.next.store

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path

class ArticleReaderTest {
    @TempDir lateinit var data: Path

    @Test fun readsPcCodePointSpansWithoutSplittingEmoji() {
        val directory = articleDirectory()
        val article = ArticleReader(data).load(directory)

        assertEquals(listOf("今日は😀。", "明日です。"), article.paragraphs)
        assertEquals("今日は😀。\n\n明日です。", article.metadata.getString("original_text"))
        assertEquals(7, article.metadata.getInt("id"))
    }

    @Test fun refusesModifiedOriginalEvenWhenManifestLooksValid() {
        val directory = articleDirectory()
        Files.writeString(data.resolve(directory).resolve("original.txt"), "改変")

        assertThrows(ArticleFormatException::class.java) { ArticleReader(data).load(directory) }
    }

    @Test fun catalogFindsThePcArticleByItsOriginalNumericIdAndDay() {
        articleDirectory()
        val catalog = ArticleCatalog(data)

        assertEquals(listOf("2026-09-29"), catalog.days())
        assertEquals(7, catalog.find(7).metadata.getInt("id"))
        assertEquals(listOf("今日の新聞"), catalog.onDay("2026-09-29").map { it.metadata.getString("title") })
    }

    @Test fun localApiServesThePcArticleWithoutChangingItsIdentity() {
        articleDirectory()
        val api = LocalLibraryApi(data)

        val response = api.request("GET", "/api/articles/7")
        assertEquals(200, response.status)
        assertEquals(7, org.json.JSONObject(response.body).getInt("id"))
        assertEquals("今日は😀。", org.json.JSONObject(response.body).getJSONArray("paragraphs").getString(0))
        assertEquals(404, api.request("GET", "/api/articles/8").status)
    }

    private fun articleDirectory(): String {
        val relative = "articles/2026-09-29/今日の新聞"
        val folder = data.resolve(relative)
        Files.createDirectories(folder)
        Files.writeString(folder.resolve("original.txt"), "今日は😀。\n\n明日です。")
        Files.writeString(folder.resolve("translation.txt"), "")
        Files.writeString(folder.resolve("furigana.html"), "")
        Files.writeString(folder.resolve("article.json"), """
            {
              "schema_version": 1,
              "revision": 2,
              "article": {"id": 7, "title": "今日の新聞", "source_name": "NHKニュース", "edition_dates": ["2026-09-29"]},
              "text_files": {
                "original.txt": {"sha256":"4d89afa81478765e718fcc9970fd9bd9f8a841d67edb4639da7f068587e7145c","field":"paragraphs","paragraphs":[[0,5],[7,12]],"whole_field":"original_text","whole_span":[0,12]},
                "translation.txt": {"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","field":"translated_paragraphs","paragraphs":[]},
                "furigana.html": {"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","field":"furigana_paragraphs","paragraphs":[]}
              },
              "assets": []
            }
        """.trimIndent())
        return relative
    }
}
