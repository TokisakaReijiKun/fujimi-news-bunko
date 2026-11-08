package jp.fujimi.newsbunko.next.news

import java.nio.file.Files
import java.nio.file.Paths
import org.json.JSONArray
import kotlin.test.*
import org.junit.jupiter.api.Test

/** Publisher HTML/API captured with PC safe downloader on 2026-10-01; no live network or paid services during tests. */
class LiveStructureRegressionTest {
    private fun fixtures():JSONArray = JSONArray(String(Files.readAllBytes(Paths.get("src/test/kotlin/jp/fujimi/newsbunko/next/news/fixtures/live-2026-10-01.json")),Charsets.UTF_8))
    @Test fun `current six official listing card structures discover article candidates`() {
        val fixtures=fixtures()
        for(i in 0 until fixtures.length()) {
            val row=fixtures.getJSONObject(i);val homepage=row.getString("homepage");val pages=row.getJSONObject("pages")
            val transport=NewsTransport { url -> val page=pages.getJSONObject(url);NewsPage(url,page.getString("finalUrl"),page.getString("html")) }
            val provider=NewsProviders.forHomepage(homepage,"設定名")
            assertTrue(provider.collect(homepage,transport,{}).isNotEmpty(),row.getString("source"))
        }
    }
    @Test fun `current six official article containers match verified PC full paragraphs`() {
        val fixtures=fixtures()
        for(i in 0 until fixtures.length()) {
            val row=fixtures.getJSONObject(i);val pages=row.getJSONObject("pages");val expected=row.getJSONObject("expected")
            val transport=NewsTransport { url -> val page=pages.getJSONObject(url);NewsPage(url,page.getString("finalUrl"),page.getString("html")) }
            val provider=NewsProviders.forHomepage(row.getString("homepage"),"設定名")
            val article=try { provider.fetchArticle(row.getString("startUrl"),transport,{}) } catch(error:Exception) {
                throw AssertionError("${row.getString("source")}：${row.getString("startUrl")} 正文回放失败：${error.message}",error)
            }
            assertEquals(expected.getString("title"),article.title,row.getString("source"))
            assertEquals((0 until expected.getJSONArray("paragraphs").length()).map { expected.getJSONArray("paragraphs").getString(it) },article.paragraphs,row.getString("source"))
            assertEquals(article.paragraphs.size,article.paragraphHtml.size)
            val rejected=row.getJSONArray("rejectedUrls")
            for(j in 0 until rejected.length()) assertFailsWith<NewsValidationException>(row.getString("source")) { provider.fetchArticle(rejected.getString(j),transport,{}) }
        }
    }
}
