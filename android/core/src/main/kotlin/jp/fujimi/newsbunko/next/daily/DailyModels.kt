package jp.fujimi.newsbunko.next.daily

import jp.fujimi.newsbunko.next.news.NewsArticle

data class DailySource(
    val id: Int,
    val name: String,
    val homepage: String,
    val minimumCount: Int = 1,
    val voiceMode: String = "inherit",
    val browserVoiceName: String = "",
)
data class DailyRequest(val date: String, val targetCount: Int, val sources: List<DailySource>)

/** Only verified, actually downloaded media belongs here. Remote preview URLs remain metadata. */
data class StoredMedia(
    val path: String,
    val bytes: ByteArray,
    val kind: String,
    val caption: String = "",
    val paragraphIndex: Int = 0,
    val sourceUrl: String = "",
)

/** Enhancement failures can preserve the original while making the final task explicitly partial. */
data class PostprocessedArticle(
    val article: NewsArticle,
    val translatedParagraphs: List<String> = emptyList(),
    val furiganaParagraphs: List<String> = emptyList(),
    val media: List<StoredMedia> = emptyList(),
    val errors: List<String> = emptyList(),
)
