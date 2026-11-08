package jp.fujimi.newsbunko.next.daily

import jp.fujimi.newsbunko.next.news.*
import jp.fujimi.newsbunko.next.store.ArticleCatalog
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Path
import java.util.concurrent.CancellationException

class DailyCoordinatorTest {
    @TempDir lateinit var data: Path
    private val transport = NewsTransport { throw AssertionError("fake provider does not need network") }
    private val day = "2026-10-01"

    @Test fun validatesEverySourceBeforePostprocessingAndOnlyProcessesSelectedCandidates() {
        val events = mutableListOf<String>()
        val providers = listOf(provider("A", 3, events), provider("B", 3, events))
        val result = coordinator(providers).run(request(2, "A", "B"), transport, { article, check ->
            check()
            assertEquals(6, events.count { it.startsWith("fetch:") })
            assertTrue(ArticleCatalog(data).onDay(day).size < 2)
            events.add("process:${article.url}")
            PostprocessedArticle(article)
        })
        assertEquals("completed", result.getString("status"))
        assertEquals(2, events.count { it.startsWith("process:") })
        assertEquals(1, result.getJSONObject("source_counts").getInt("A"))
        assertEquals(1, result.getJSONObject("source_counts").getInt("B"))
        assertEquals(2, ArticleCatalog(data).onDay(day).size)
    }

    @Test fun missingSourceQuotaStaysPartialEvenWhenTotalTargetIsReached() {
        val result = coordinator(listOf(provider("A", 3), provider("B", 0)))
            .run(request(2, "A", "B"), transport, { article, _ -> PostprocessedArticle(article) })
        assertEquals("partial", result.getString("status"))
        assertEquals(2, result.getInt("completed"))
        assertEquals("B", result.getJSONArray("missing_sources").getString(0))
        assertTrue(result.getInt("percent") < 100)
    }

    @Test fun sameDayRetryReusesExistingAndPrioritizesMissingSource() {
        coordinator(listOf(provider("A", 2), provider("B", 0)))
            .run(request(2, "A", "B"), transport, { article, _ -> PostprocessedArticle(article) })
        val before = ArticleCatalog(data).onDay(day).associate { it.metadata.getLong("id") to it.manifest.toString() }
        val processed = mutableListOf<String>()
        val result = coordinator(listOf(provider("A", 2), provider("B", 1)))
            .run(request(2, "A", "B"), transport, { article, _ ->
                processed.add(article.publisher)
                PostprocessedArticle(article)
            })
        assertEquals(listOf("B"), processed)
        assertEquals("completed", result.getString("status"))
        assertEquals(3, ArticleCatalog(data).onDay(day).size)
        before.forEach { (id, manifest) -> assertEquals(manifest, ArticleCatalog(data).find(id).manifest.toString()) }
    }

    @Test fun invalidCandidatesAreExcludedNotReportedAsUncollectedErrorsAndLimitIsFive() {
        val events = mutableListOf<String>()
        val bad = provider("A", 12, events, excluded = true)
        val result = coordinator(listOf(bad)).run(request(1, "A"), transport, { _, _ ->
            fail<PostprocessedArticle>("must not postprocess invalid article")
        })
        assertEquals("failed", result.getString("status"))
        assertEquals(5, events.count { it.startsWith("fetch:") })
        assertEquals(0, result.getJSONArray("errors").length())
        val stats = result.getJSONObject("candidate_stats").getJSONObject("A")
        assertEquals(5, stats.getInt("invalid_excluded"))
        assertTrue(stats.getString("last_reason").contains("会员"))
    }

    @Test fun listFailureAndPostprocessFailureGoToErrorsAndDoNotCountAsSaved() {
        val badList = object : NewsProvider {
            override val name = "B"
            override fun collect(homepage: String, transport: NewsTransport, checkpoint: () -> Unit): List<String> = throw IllegalStateException("列表失败")
            override fun fetchArticle(url: String, transport: NewsTransport, checkpoint: () -> Unit): NewsArticle = error("not called")
        }
        val result = coordinator(listOf(provider("A", 1), badList)).run(request(2, "A", "B"), transport, { _, _ ->
            throw IllegalStateException("后处理失败")
        })
        assertEquals("failed", result.getString("status"))
        assertEquals(2, result.getJSONArray("errors").length())
        assertEquals(0, result.getInt("completed"))
    }

    @Test fun cancellationAfterARequestCannotWriteFilesOrPublishAnyFurtherProgress() {
        var cancelled = false
        var progressCount = 0
        val articles = provider("A", 1)
        val delaying = object : NewsProvider by articles {
            override fun fetchArticle(url: String, transport: NewsTransport, checkpoint: () -> Unit): NewsArticle {
                val result = articles.fetchArticle(url, transport, checkpoint)
                cancelled = true
                return result
            }
        }
        assertThrows(CancellationException::class.java) {
            coordinator(listOf(delaying)).run(request(1, "A"), transport,
                { _, _ -> fail<PostprocessedArticle>("cancelled task must not postprocess") },
                checkpoint = { if (cancelled) throw CancellationException("中止") },
                onProgress = { assertFalse(cancelled); progressCount++ })
        }
        assertTrue(progressCount > 0)
        assertTrue(ArticleCatalog(data).onDay(day).isEmpty())
    }

    @Test fun optionalEnhancementFailurePreservesOriginalAndReportsPartial() {
        val result = coordinator(listOf(provider("A", 1))).run(request(1, "A"), transport,
            { article, _ -> PostprocessedArticle(article, errors = listOf("翻译失败：未配置密钥")) })
        assertEquals("partial", result.getString("status"))
        assertEquals(1, result.getInt("completed"))
        assertEquals(1, result.getJSONArray("errors").length())
        assertEquals(listOf("公開正文です。"), ArticleCatalog(data).onDay(day).single().paragraphs)
    }

    @Test fun sourceNoneStaysSilentAndBrowserAndInheritKeepTheSelectedEdgeVoiceWithoutSavedAudio() {
        val names = listOf("A", "B", "C")
        val sources = listOf(
            DailySource(1, "A", "https://example.test/A", 1, voiceMode = "none", browserVoiceName = "ja-JP-NanamiNeural"),
            DailySource(2, "B", "https://example.test/B", 1, voiceMode = "browser", browserVoiceName = "ja-JP-NanamiNeural"),
            DailySource(3, "C", "https://example.test/C", 1, voiceMode = "inherit", browserVoiceName = "ja-JP-NanamiNeural"),
        )
        coordinator(names.map { provider(it, 1) }).run(DailyRequest(day, 3, sources), transport,
            { article, _ -> PostprocessedArticle(article) })
        val articles = ArticleCatalog(data).onDay(day).associate { it.metadata.getString("source_name") to it.metadata }
        val silent = articles.getValue("A")
        assertEquals("none", silent.getString("source_voice_mode"))
        assertEquals("none", silent.getString("voice_mode"))
        assertEquals("disabled", silent.getString("audio_status"))
        assertEquals("", silent.getString("audio_path"))
        for (name in listOf("B", "C")) {
            val article = articles.getValue(name)
            assertEquals(if (name == "B") "browser" else "inherit", article.getString("source_voice_mode"))
            assertEquals("browser", article.getString("voice_mode"))
            assertEquals("browser", article.getString("audio_voice_mode"))
            assertEquals("ja-JP-NanamiNeural", article.getString("browser_voice_name"))
            assertEquals("browser", article.getString("audio_status"))
            assertEquals("", article.getString("audio_path"))
        }
    }

    @Test fun authorizedRemoteNhkVideoIsKeptInArticleMetadataWhenNoLocalCopyExists() {
        val video = "https://media.vd.st.nhk/example/clip.m3u8"
        val source = object : NewsProvider {
            override val name = "NHKニュース"
            override fun collect(homepage: String, transport: NewsTransport, checkpoint: () -> Unit) = listOf("https://example.test/nhk/1")
            override fun fetchArticle(url: String, transport: NewsTransport, checkpoint: () -> Unit) =
                NewsArticle(url, "NHK", name, listOf("公開正文です。"), media = listOf(NewsMedia(video, "video")))
        }
        coordinator(listOf(source)).run(request(1, "NHKニュース"), transport,
            { article, _ -> PostprocessedArticle(article) })
        val metadata = ArticleCatalog(data).onDay(day).single().metadata
        assertEquals(video, metadata.getJSONArray("video_urls").getString(0))
        assertEquals("preview", metadata.getString("video_status"))
    }

    private fun request(target: Int, vararg names: String) = DailyRequest(day, target,
        names.mapIndexed { index, name -> DailySource(index + 1, name, "https://example.test/$name", 1) })

    private fun coordinator(providers: List<NewsProvider>) = DailyCoordinator(data) { source ->
        providers.single { it.name == source.name }
    }

    private fun provider(sourceName: String, count: Int, events: MutableList<String> = mutableListOf(), excluded: Boolean = false) = object : NewsProvider {
        override val name = sourceName
        override fun collect(homepage: String, transport: NewsTransport, checkpoint: () -> Unit): List<String> {
            checkpoint()
            events.add("collect:$name")
            return (1..count).map { "https://example.test/$name/$it" }
        }
        override fun fetchArticle(url: String, transport: NewsTransport, checkpoint: () -> Unit): NewsArticle {
            checkpoint()
            events.add("fetch:$url")
            if (excluded) throw NewsValidationException("会员正文")
            return NewsArticle(url, "$name ${url.substringAfterLast('/')}", name, listOf("公開正文です。"))
        }
    }
}
