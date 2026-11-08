package jp.fujimi.newsbunko.next.daily

import jp.fujimi.newsbunko.next.news.NewsArticle
import jp.fujimi.newsbunko.next.news.NewsProvider
import jp.fujimi.newsbunko.next.news.NewsProviders
import jp.fujimi.newsbunko.next.news.NewsTransport
import jp.fujimi.newsbunko.next.news.NewsValidationException
import jp.fujimi.newsbunko.next.store.ArticleCatalog
import jp.fujimi.newsbunko.next.store.ArticleStore
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.URI
import java.nio.file.Path
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.util.concurrent.CancellationException

/** Three phases with a per-run state object. No candidate request can write an article. */
class DailyCoordinator(
    private val dataRoot: Path,
    private val providerFactory: (DailySource) -> NewsProvider = { NewsProviders.forHomepage(it.homepage, it.name) },
) {
    fun run(
        request: DailyRequest,
        transport: NewsTransport,
        postprocess: (NewsArticle, () -> Unit) -> PostprocessedArticle,
        checkpoint: () -> Unit = {},
        onProgress: (JSONObject) -> Unit = {},
    ): JSONObject {
        LocalDate.parse(request.date)
        require(request.targetCount in 1..500 && request.sources.isNotEmpty()) { "日刊目标或来源无效。" }
        require(request.sources.all { it.minimumCount in 0..100 && it.name.isNotBlank() && it.homepage.isNotBlank() }) { "来源最低配额无效。" }
        require(request.sources.all { it.voiceMode in setOf("none", "browser", "inherit") }) { "Android 来源仅支持即时 Edge 朗读、沿用全局或无朗读。" }
        require(request.sources.map { it.name }.distinct().size == request.sources.size &&
            request.sources.map { it.id }.distinct().size == request.sources.size) { "日刊来源重复。" }
        checkpoint()
        val store = ArticleStore(dataRoot)
        store.recover()
        checkpoint()
        val existing = ArticleCatalog(dataRoot).onDay(request.date).filter {
            it.paragraphs.isNotEmpty() && it.metadata.optString("status", "ready") == "ready"
        }
        val accepted = existing.map { it.metadata.getLong("id") }.toMutableSet()
        val knownUrls = existing.map { it.metadata.optString("url") }.filter { it.isNotEmpty() }.toMutableSet()
        val counts = request.sources.associate { source -> source.name to existing.count {
            it.metadata.optString("source_name") == source.name
        } }.toMutableMap()
        val target = maxOf(request.targetCount, request.sources.sumOf { it.minimumCount })
        val errors = mutableListOf<String>()
        val stats = JSONObject()
        val pools = linkedMapOf<DailySource, MutableList<NewsArticle>>()
        var plannedTotal = maxOf(target, accepted.size)
        val state = JSONObject().put("status", "running").put("stage", "starting").put("date", request.date)
            .put("pipeline_version", 8).put("total", plannedTotal).put("completed", accepted.size)
            .put("selected", accepted.size).put("percent", 0).put("current", "")
            .put("source_counts", JSONObject(counts)).put("missing_sources", JSONArray())
            .put("errors", JSONArray()).put("candidate_stats", stats)

        fun emit(stage: String, message: String, current: String = "") {
            checkpoint()
            state.put("stage", stage).put("message", message).put("current", current)
                .put("completed", accepted.size).put("total", plannedTotal)
                .put("source_counts", JSONObject(counts)).put("errors", JSONArray(errors))
                .put("percent", if (stage == "complete") 100 else minOf(99, accepted.size * 100 / plannedTotal))
            onProgress(JSONObject(state.toString()))
        }

        fun finish(): JSONObject {
            checkpoint()
            val missing = request.sources.filter { counts.getValue(it.name) < it.minimumCount }.map { it.name }
            val complete = accepted.size >= plannedTotal && missing.isEmpty() && errors.isEmpty()
            val status = if (complete) "completed" else if (accepted.isNotEmpty()) "partial" else "failed"
            state.put("status", status).put("missing_sources", JSONArray(missing))
            val message = "日刊 ${accepted.size}/$plannedTotal 篇。" +
                (if (missing.isNotEmpty()) "未满足来源配额：${missing.joinToString("、")}。" else "") +
                (if (errors.isNotEmpty()) "${errors.size} 项读取或后处理失败。" else "")
            emit(if (complete) "complete" else status, message)
            return JSONObject(state.toString())
        }

        emit("starting", "准备独立采集日刊；复用当日有效文章。")
        if (accepted.size >= target && request.sources.all { counts.getValue(it.name) >= it.minimumCount }) return finish()

        // Phase 1: source-owned public-body validation only, bounded to five candidates per source.
        for (source in request.sources) {
            checkpoint()
            val sourceStats = JSONObject().put("listed", 0).put("examined", 0).put("public", 0)
                .put("invalid_excluded", 0).put("network_failed", 0).put("last_reason", "").put("reasons", JSONArray())
            stats.put(source.name, sourceStats)
            val candidates = mutableListOf<NewsArticle>()
            pools[source] = candidates
            emit("collecting", "${source.name}：读取候选列表", source.homepage)
            val provider: NewsProvider
            val links: List<String>
            try {
                provider = providerFactory(source)
                checkpoint()
                links = provider.collect(source.homepage, transport, checkpoint).distinct()
                    .filter { it !in knownUrls }.take(5)
                checkpoint()
            } catch (error: Exception) {
                rethrowCancellation(error, checkpoint)
                errors.add("${source.name}：候选列表读取失败（${error.javaClass.simpleName}）")
                sourceStats.put("network_failed", 1)
                emit("collecting", "${source.name}：候选列表读取失败")
                continue
            }
            sourceStats.put("listed", links.size)
            for (url in links) {
                checkpoint()
                sourceStats.put("examined", sourceStats.getInt("examined") + 1)
                emit("collecting", "${source.name}：验证公开正文 ${sourceStats.getInt("examined")}/${links.size}", url)
                try {
                    val article = provider.fetchArticle(url, transport, checkpoint)
                    checkpoint()
                    if (article.title.isBlank() || article.paragraphs.isEmpty() || article.paragraphs.any { it.isBlank() }) {
                        throw NewsValidationException("正文或标题无效")
                    }
                    if (article.url in knownUrls || candidates.any { it.url == article.url }) {
                        sourceStats.put("last_reason", "同日已收录或重复候选")
                    } else {
                        candidates.add(article)
                        sourceStats.put("public", sourceStats.getInt("public") + 1)
                    }
                } catch (error: Exception) {
                    rethrowCancellation(error, checkpoint)
                    val network = error is IOException
                    val field = if (network) "network_failed" else "invalid_excluded"
                    sourceStats.put(field, sourceStats.getInt(field) + 1)
                    val reason = if (error is NewsValidationException) error.reason.take(180)
                        else if (network) "正文请求失败（${error.javaClass.simpleName}）"
                        else "正文校验失败（${error.javaClass.simpleName}）"
                    sourceStats.put("last_reason", reason)
                    sourceStats.getJSONArray("reasons").put(JSONObject().put("url", url)
                        .put("kind", if (network) "request" else "parse").put("detail", reason))
                }
                emit("collecting", "${source.name}：公开 ${sourceStats.getInt("public")} 篇；${sourceStats.optString("last_reason")}", url)
            }
        }

        // Phase 2: quota-first selection entirely in memory. Existing articles are never removed.
        emit("selecting", "先补齐缺失来源，再补足日刊目标。")
        val selected = mutableListOf<Pair<DailySource, NewsArticle>>()
        val selectedCounts = counts.toMutableMap()
        val selectedUrls = knownUrls.toMutableSet()
        fun choose(source: DailySource): Boolean {
            val pool = pools.getValue(source)
            while (pool.isNotEmpty()) {
                val article = pool.removeAt(0)
                if (selectedUrls.add(article.url)) {
                    selected.add(source to article)
                    selectedCounts[source.name] = selectedCounts.getValue(source.name) + 1
                    return true
                }
            }
            return false
        }
        do {
            var changed = false
            for (source in request.sources) {
                if (selectedCounts.getValue(source.name) < source.minimumCount) changed = choose(source) || changed
            }
        } while (changed)
        // Round-robin filling keeps configured list order from monopolizing remaining slots.
        while (accepted.size + selected.size < target) {
            var changed = false
            for (source in request.sources) {
                if (accepted.size + selected.size >= target) break
                changed = choose(source) || changed
            }
            if (!changed) break
        }
        plannedTotal = maxOf(target, accepted.size + selected.size)
        state.put("selected", accepted.size + selected.size)
        emit("selecting", "已从公开候选选择 ${accepted.size + selected.size}/$plannedTotal 篇。")

        // Phase 3: only selected new articles may translate, download media, or create files.
        for ((index, item) in selected.withIndex()) {
            val (source, article) = item
            checkpoint()
            emit("processing", "后处理 ${index + 1}/${selected.size}：${source.name}", article.url)
            try {
                emit("enhancing", "${source.name}：生成假名与翻译", article.url)
                val enhanced = postprocess(article, checkpoint)
                checkpoint()
                require(enhanced.article.url == article.url && enhanced.article.paragraphs == article.paragraphs) {
                    "后处理不得改变文章归属或原文。"
                }
                emit("media", "${source.name}：提交正文与已下载媒体", article.url)
                val saved = store.create(metadata(source, enhanced, request.date), request.date, enhanced.media, checkpoint)
                checkpoint()
                if (accepted.add(saved.metadata.getLong("id"))) counts[source.name] = counts.getValue(source.name) + 1
                knownUrls.add(saved.metadata.optString("url"))
                errors.addAll(enhanced.errors.map { "${source.name}：${it.take(240)}" })
            } catch (error: Exception) {
                rethrowCancellation(error, checkpoint)
                errors.add("${source.name}：后处理失败（${error.javaClass.simpleName}）")
            }
            emit("processing", "已保存 ${accepted.size}/$plannedTotal 篇。")
        }
        return finish()
    }

    private fun metadata(source: DailySource, enhanced: PostprocessedArticle, day: String): JSONObject {
        val article = enhanced.article
        val images = enhanced.media.filter { it.kind == "image" }
        val videos = enhanced.media.filter { it.kind == "video" }
        val videoPreviews = article.media.filter { it.kind == "video" && videos.none { local -> local.sourceUrl == it.url } }
        val ruby = enhanced.furiganaParagraphs.ifEmpty { article.paragraphHtml }
        val now = OffsetDateTime.now(ZoneOffset.ofHours(8))
        val voiceMode = if (source.voiceMode == "none") "none" else "browser"
        return JSONObject().put("title", article.title).put("url", article.url)
            .put("source_name", source.name).put("source_key", sourceKey(article.url)).put("publisher_name", article.publisher)
            .put("published_at", article.publishedAt).put("created_at", if (now.toLocalDate().toString() == day) now.toString() else "${day}T00:00:00+08:00")
            .put("status", "ready").put("failure_reason", "").put("edition_dates", JSONArray(listOf(day)))
            .put("paragraphs", JSONArray(article.paragraphs)).put("translated_paragraphs", JSONArray(enhanced.translatedParagraphs))
            .put("furigana_paragraphs", JSONArray(ruby)).put("page_urls", JSONArray(article.pageUrls))
            .put("image_paths", JSONArray(images.map { it.path })).put("image_urls", JSONArray(images.map { it.sourceUrl }))
            .put("image_links", JSONArray(images.map { it.sourceUrl }))
            .put("image_captions", JSONArray(images.map { it.caption })).put("image_positions", JSONArray(images.map { it.paragraphIndex }))
            .put("video_urls", JSONArray(videos.map { it.path } + videoPreviews.map { it.url }))
            .put("video_captions", JSONArray(videos.map { it.caption } + videoPreviews.map { it.caption }))
            .put("video_positions", JSONArray(videos.map { it.paragraphIndex } + videoPreviews.map { it.paragraphIndex }))
            .put("video_status", if (videoPreviews.isNotEmpty()) "preview" else if (videos.isNotEmpty()) "cached" else "none")
            .put("media_warnings", JSONArray(article.mediaWarnings))
            .put("translation_error", enhanced.errors.filter { it.contains("翻译") }.joinToString("；"))
            .put("source_voice_mode", source.voiceMode).put("voice_mode", voiceMode).put("audio_voice_mode", voiceMode)
            .put("browser_voice_name", if (voiceMode == "browser") source.browserVoiceName else "")
            .put("audio_voice_name", if (voiceMode == "browser") source.browserVoiceName else "")
            .put("audio_voice_id", JSONObject.NULL)
            .put("audio_status", if (voiceMode == "none") "disabled" else "browser").put("audio_path", "")
    }

    private fun rethrowCancellation(error: Exception, checkpoint: () -> Unit) {
        if (error is CancellationException || error is InterruptedException) throw error
        checkpoint()
    }

    private fun sourceKey(url: String): String {
        val host = URI(url).host.orEmpty().lowercase()
        return mapOf("news.web.nhk" to "nhk", "nhk.or.jp" to "nhk", "asahi.com" to "asahi",
            "yomiuri.co.jp" to "yomiuri", "nikkei.com" to "nikkei", "sankei.com" to "sankei",
            "news.yahoo.co.jp" to "yahoo").entries.firstOrNull {
            host == it.key || host.endsWith(".${it.key}")
        }?.value ?: "custom"
    }
}
