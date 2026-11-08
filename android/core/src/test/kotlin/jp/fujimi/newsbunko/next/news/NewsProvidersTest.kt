package jp.fujimi.newsbunko.next.news

import kotlin.test.*
import org.junit.jupiter.api.Test

class NewsProvidersTest {
    private val nhk = "https://news.web.nhk/newsweb/na/na-k10015000001000"
    private val asahi = "https://www.asahi.com/articles/AS123ABC.html"
    private val yomiuri = "https://www.yomiuri.co.jp/national/20261001-OYT1T50001/"
    private val nikkei = "https://www.nikkei.com/article/DGXZQOUA123450/"
    private val sankei = "https://www.sankei.com/article/20261001-ABC123/"
    private val yahoo = "https://news.yahoo.co.jp/articles/" + "a".repeat(40)
    private fun provider(url: String) = NewsProviders.forHomepage(url, "設定名")
    private fun fetch(url: String, html: String): NewsArticle = provider(url).fetchArticle(url, NewsTransport { NewsPage(it, it, html) }, {})
    private fun page(body: String) = "<html><head><title>公開ニュース</title></head><body><h1>公開ニュース</h1>$body</body></html>"
    private val fixtures get() = listOf(
        nhk to page("<div class='content--detail-body'><p>本文です。</p><div class='recommend'><p>推薦記事</p><img src='/wrong.jpg'></div></div>"),
        asahi to page("<main><div class='ArticleText'><p>本文です。</p></div></main>"),
        yomiuri to page("<article class='article-content'><div class='p-main-contents'><p itemprop='articleBody'>本文です。</p><p>記事をシェアする</p><p>完了しました</p><figure><img src='/photo.jpg'><figcaption>会場</figcaption></figure></div></article>"),
        nikkei to page("<main id='main-content'><article><h1>公開ニュース</h1><div data-track-article-content><p class='paragraph_abc'>本文です。</p></div></article></main>"),
        sankei to page("<article class='article-wrapper'><div class='article-body'><p class='article-text'>本文です。</p><p>関連カード</p><figure class='article-image'><img src='/photo.jpg'><figcaption>会場</figcaption></figure></div></article>"),
        yahoo to page("<article id='uamods'><h1>公開ニュース</h1><div class='article_body'><p class='yjSlinkDirectlink'>本文です。</p><aside><p class='yjSlinkDirectlink'>推薦記事</p></aside></div></article>"),
    )
    @Test fun `six publishers keep only their recognized report paragraphs`() {
        fixtures.forEach { (url, html) ->
            val article = fetch(url, html)
            assertEquals(listOf("本文です。"), article.paragraphs, url)
            assertEquals("公開ニュース", article.title)
            assertEquals(url, article.url)
        }
        assertEquals("会場", fetch(yomiuri, fixtures[2].second).media.single().caption)
        assertEquals("会場", fetch(sankei, fixtures[4].second).media.single().caption)
        assertTrue(fetch(nhk, fixtures[0].second).media.isEmpty())
    }
    @Test fun `all publishers reject paid metadata and unknown body containers`() {
        fixtures.forEach { (url, html) ->
            val paid = html.replace("</head>", "<script type='application/ld+json'>{\"@type\":\"NewsArticle\",\"isAccessibleForFree\":false}</script></head>")
            assertFailsWith<NewsValidationException> { fetch(url, paid) }
            assertFailsWith<NewsValidationException> { fetch(url, page("<p>摘要</p>")) }
        }
    }
    @Test fun `known publisher original URL cannot redirect to another article or site`() {
        assertFailsWith<NewsValidationException> {
            provider(asahi).fetchArticle(asahi, NewsTransport { NewsPage(it, "https://example.org/articles/AS123ABC.html", fixtures[1].second) }, {})
        }
        assertFailsWith<NewsValidationException> {
            provider(nhk).fetchArticle(nhk, NewsTransport { NewsPage(it, nhk + "other", fixtures[0].second) }, {})
        }
    }
    @Test fun `asahi membership badge and sankei paid wrapper reject teaser`() {
        assertFailsWith<NewsValidationException> { fetch(asahi, fixtures[1].second.replace("<h1>", "<header><img alt='有料記事'><h1>").replace("</h1>", "</h1></header>")) }
        assertFailsWith<NewsValidationException> { fetch(sankei, fixtures[4].second.replace("article-wrapper", "article-wrapper paid_members")) }
    }
    @Test fun `nikkei anonymous unlocked tail advert is allowed but actual locks are rejected`() {
        fun html(locked: Boolean) = fixtures[3].second.replace("</body>", "<script id='js-k2-hydrate-client-exposed-context'>{\"paywallProps\":{\"kijiId\":\"DGXZQOUA123450\",\"lockStatus\":{\"type\":\"anonymous\",\"isLocked\":$locked,\"isDynamicLocked\":false},\"isLockedArticle\":false,\"isPaidUserOnlyArticle\":false}}</script></body>").replace("</article>", "<div class='mainPaywall_promo'>有料会員になると</div></article>")
        assertEquals(listOf("本文です。"), fetch(nikkei, html(false)).paragraphs)
        assertFailsWith<NewsValidationException> { fetch(nikkei, html(true)) }
        assertFailsWith<NewsValidationException> { fetch(nikkei, fixtures[3].second.replace("</article>", "<div class='mainPaywall_promo'>会員限定</div></article>")) }
    }
    @Test fun `Yahoo pickup validates all pages and refuses cached page one or changed entity`() {
        val pickup = "https://news.yahoo.co.jp/pickup/1234567"
        val one = fixtures[5].second.replace("</body>", "<a href='$yahoo?page=2'>次へ</a></body>")
        val two = fixtures[5].second.replace("本文です。", "第二頁です。")
        val transport = NewsTransport { u -> NewsPage(u, u, when(u) {
            pickup -> page("<a href='$yahoo'>記事全文を読む</a>")
            yahoo -> one
            "$yahoo?page=2" -> two
            else -> error("unexpected $u")
        }) }
        val article = provider(yahoo).fetchArticle(pickup, transport, {})
        assertEquals(listOf("本文です。", "第二頁です。"), article.paragraphs)
        assertEquals(listOf(yahoo, "$yahoo?page=2"), article.pageUrls)
        assertFailsWith<NewsValidationException> { provider(yahoo).fetchArticle(yahoo, NewsTransport { u -> if(u.endsWith("page=2")) NewsPage(u,yahoo,two) else NewsPage(u,u,one) }, {}) }
        assertFailsWith<NewsValidationException> { provider(yahoo).fetchArticle(yahoo, NewsTransport { u -> if(u.endsWith("page=2")) NewsPage(u,yahoo.replace('a','b'),two) else NewsPage(u,u,one) }, {}) }
        assertFailsWith<NewsValidationException> { provider(yahoo).fetchArticle(yahoo, NewsTransport { u -> NewsPage(u,u,one) }, {}) }
    }
    @Test fun `listing eliminates paid cards and query variants without trusting setting name`() {
        val html = "<li><a href='$asahi?ref=top'>公開</a></li><li><a href='https://www.asahi.com/articles/ASPAID.html'>有料会員記事</a><img alt='有料記事'></li><a href='$asahi#fragment'>公開</a>"
        assertEquals(listOf(asahi), provider(asahi).collect("https://www.asahi.com/", NewsTransport { NewsPage(it,it,html) }, {}))
        assertEquals("朝日新聞", provider(asahi).name)
    }
    @Test fun `cancellation after network prevents parsing returned page`() {
        var returned = false
        assertFailsWith<InterruptedException> { provider(asahi).fetchArticle(asahi, NewsTransport { returned=true; NewsPage(it,it,fixtures[1].second) }, { if(returned) throw InterruptedException("中止") }) }
    }
    @Test fun `safe ruby keeps readings but no scripts or remote attributes`() {
        val result = fetch(asahi, fixtures[1].second.replace("本文です。", "<ruby onclick='evil()'><rb>日本</rb><rt>にほん</rt></ruby><script>evil()</script>のニュース。"))
        assertEquals(listOf("日本のニュース。"), result.paragraphs)
        assertEquals(listOf("<ruby><rb>日本</rb><rt>にほん</rt></ruby>のニュース。"), result.paragraphHtml)
    }
    @Test fun `NHK current API checks identity and refuses summary`() {
        val shell = page("<script id='json-ld-article' type='application/ld+json'>{\"@type\":\"NewsArticle\",\"headline\":\"ニュース\"}</script>")
        fun api(body: String, id: String = "na-k10015000001000") = "{\"type\":\"NewsArticle\",\"id\":\"$id\",\"canonical\":\"$nhk\",\"headline\":\"公開ニュース\",\"articleBody\":\"$body\"}"
        val transport = NewsTransport { u -> NewsPage(u,u,if(u==nhk) shell else api("本文です。")) }
        assertEquals(listOf("本文です。"), provider(nhk).fetchArticle(nhk,transport,{}).paragraphs)
        assertFailsWith<NewsValidationException> { provider(nhk).fetchArticle(nhk,NewsTransport { u -> NewsPage(u,u,if(u==nhk) shell else api("本文です。","wrong")) },{}) }
        assertFailsWith<NewsValidationException> { provider(nhk).fetchArticle(nhk,NewsTransport { u -> NewsPage(u,u,when { u==nhk -> shell; u.contains("area.json") -> "{\"country_name\":\"Japan\"}"; else -> api("") }) },{}) }
    }
    @Test fun `Nikkei boxed text appears once with heading and emphasized text`() {
        val html=fixtures[3].second.replace("<p class='paragraph_abc'>本文です。</p>","<div class='container_c1tzahnc'><h2>要点</h2><p class='paragraph_abc'>本文の<strong>核心</strong>です。</p></div>")
        val article=fetch(nikkei,html)
        assertEquals(1,article.paragraphs.size)
        assertTrue(article.paragraphs.single().contains("本文の核心です。"))
        assertTrue(article.paragraphHtml.single().contains("<strong>核心</strong>"))
    }
    @Test fun `Asahi signup advertising outside public body is not a report paywall`() {
        val html=fixtures[1].second.replace("</main>","<aside><p>この記事を読むには有料会員登録が必要です</p></aside></main>")
        assertEquals(listOf("本文です。"),fetch(asahi,html).paragraphs)
    }
}
