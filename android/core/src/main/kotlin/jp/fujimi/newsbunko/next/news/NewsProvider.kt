package jp.fujimi.newsbunko.next.news

data class NewsPage(val requestedUrl: String, val finalUrl: String, val html: String)
fun interface NewsTransport { fun get(url: String): NewsPage }
data class NewsMedia(val url: String, val kind: String, val caption: String = "", val paragraphIndex: Int = 0)
data class NewsArticle(
    val url: String, val title: String, val publisher: String, val paragraphs: List<String>,
    val publishedAt: String = "", val media: List<NewsMedia> = emptyList(),
    val pageUrls: List<String> = emptyList(), val mediaWarnings: List<String> = emptyList(),
    val paragraphHtml: List<String> = emptyList(),
)
class NewsValidationException(val reason: String) : IllegalArgumentException(reason)
interface NewsProvider {
    val name: String
    val processingSteps: List<String> get() = listOf("kana", "translation", "media")
    fun collect(homepage: String, transport: NewsTransport, checkpoint: () -> Unit): List<String>
    fun fetchArticle(url: String, transport: NewsTransport, checkpoint: () -> Unit): NewsArticle
}

object NewsProviders {
    val defaults: List<NewsProvider> = listOf(NhkProvider, AsahiProvider, YomiuriProvider, NikkeiProvider, SankeiProvider, YahooProvider)
    fun forHomepage(homepage: String, name: String): NewsProvider {
        val host = NewsPrimitives.uri(homepage).host.orEmpty().lowercase()
        return when {
            NewsPrimitives.hostMatches(host, listOf("news.web.nhk", "nhk.or.jp")) -> NhkProvider
            NewsPrimitives.hostMatches(host, listOf("asahi.com")) -> AsahiProvider
            NewsPrimitives.hostMatches(host, listOf("yomiuri.co.jp")) -> YomiuriProvider
            NewsPrimitives.hostMatches(host, listOf("nikkei.com")) -> NikkeiProvider
            NewsPrimitives.hostMatches(host, listOf("sankei.com")) -> SankeiProvider
            host == "news.yahoo.co.jp" -> YahooProvider
            else -> CustomProvider(host, name)
        }
    }
}
