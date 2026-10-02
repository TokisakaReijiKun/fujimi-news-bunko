package jp.fujimi.newsbunko.next

import androidx.test.ext.junit.runners.AndroidJUnit4
import jp.fujimi.newsbunko.next.daily.ArticlePostprocessor
import jp.fujimi.newsbunko.next.daily.PublicHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.net.InetAddress
import java.util.Base64

/** Runs real Android/OkHttp address handling without any network or user data. */
@RunWith(AndroidJUnit4::class)
class DailyDeviceTest {
    @Test fun offlineIpadicPreservesSuppliedRubyAndProducesReadablePcFiles() {
        val context = androidx.test.core.app.ApplicationProvider.getApplicationContext<android.content.Context>()
        // This test never invokes a paid service, even if run on a configured test profile.
        org.junit.Assume.assumeFalse(jp.fujimi.newsbunko.next.settings.SecretStore(context).isConfigured())
        val article = jp.fujimi.newsbunko.next.news.NewsArticle(
            "https://www.yomiuri.co.jp/national/20261001-OYT1T50000/", "日本の新聞😀", "読売新聞",
            listOf("日本の新聞です。", "東京で本を読みます。"),
            paragraphHtml = listOf("<ruby>日本<rt>にっぽん</rt></ruby>の新聞です。", "東京で本を読みます。"),
        )
        val steps = mutableListOf<String>()
        val enhanced = ArticlePostprocessor(context, PublicHttpClient(context) {}) { stage, _ -> steps += stage }
            .process(article) { }
        assertTrue(enhanced.errors.toString(), enhanced.errors.isEmpty())
        assertEquals(2, enhanced.furiganaParagraphs.size)
        assertTrue(enhanced.furiganaParagraphs[0].contains("<rt>にっぽん</rt>"))
        assertFalse(enhanced.furiganaParagraphs[0].contains("<ruby><ruby>"))
        assertTrue(enhanced.furiganaParagraphs[1].contains("<ruby>"))
        assertTrue(steps.contains("enhancing"))
        val root = java.nio.file.Files.createTempDirectory(context.cacheDir.toPath(), "kana-store-")
        try {
            val input = org.json.JSONObject().put("title", article.title).put("url", article.url)
                .put("paragraphs", org.json.JSONArray(article.paragraphs))
                .put("furigana_paragraphs", org.json.JSONArray(enhanced.furiganaParagraphs))
            val saved = jp.fujimi.newsbunko.next.store.ArticleStore(root).create(input, "2026-10-01")
            val read = jp.fujimi.newsbunko.next.store.ArticleReader(root).load(saved.directory)
            assertEquals(article.paragraphs, read.paragraphs)
            assertEquals(enhanced.furiganaParagraphs[0], read.metadata.getJSONArray("furigana_paragraphs").getString(0))
        } finally { root.toFile().deleteRecursively() }
    }

    @Test fun checkedUrlsRejectLocalHostsAndUnsafeTransport() {
        val rejected = listOf(
            "http://example.org/news", "ftp://example.org/news", "file:///news.html",
            "https://localhost/news", "https://news.localhost/news", "https://device.local/news",
            "https://reader@example.org/news", "https://reader:fixture@example.org/news",
            "https://example.org:8443/news",
        )
        rejected.forEach { value ->
            try {
                PublicHttpClient.checkedUrl(value)
                fail("Unsafe news URL was accepted: $value")
            } catch (_: IllegalArgumentException) { }
        }
        assertEquals("example.org", PublicHttpClient.checkedUrl("https://example.org/news?id=1").host)
        assertEquals("8.8.8.8", PublicHttpClient.checkedUrl("https://8.8.8.8/news").host)
        assertEquals("2606:4700:4700::1111", PublicHttpClient.checkedUrl("https://[2606:4700:4700::1111]/news").host)
    }

    @Test fun actualConnectionAddressesRejectPrivateLocalAndSharedRanges() {
        // Numeric addresses are parsed locally, so this test never resolves DNS.
        val rejected = listOf(
            "0.0.0.0", "127.0.0.1", "127.10.20.30", "10.1.2.3",
            "172.16.0.1", "172.31.255.254", "192.168.1.2",
            "100.64.0.1", "100.127.255.254", "169.254.1.2",
            "224.0.0.1", "255.255.255.255",
            "192.0.2.1", "198.18.0.1", "198.51.100.1", "203.0.113.1",
            "::", "::1", "fe80::1", "fc00::1", "fd12:3456:789a::1", "ff02::1",
            "2001:db8::1", "::ffff:127.0.0.1", "::ffff:10.1.2.3",
        )
        rejected.forEach { address ->
            assertFalse("Nonpublic connection address was accepted: $address", PublicHttpClient.isPublic(InetAddress.getByName(address)))
        }
        listOf("8.8.8.8", "1.1.1.1", "100.63.255.254", "100.128.0.1", "2001:4860:4860::8888", "2606:4700:4700::1111").forEach { address ->
            assertTrue("Public connection address was rejected: $address", PublicHttpClient.isPublic(InetAddress.getByName(address)))
        }
    }

    @Test fun mediaChecksRejectHtmlErrorPagesAndUnverifiedVideoBodies() {
        val png = Base64.getDecoder().decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jF1sAAAAASUVORK5CYII=")
        assertTrue("Real PNG fixture should be accepted", ArticlePostprocessor.validMedia(png, "image"))
        assertFalse("An image is not a downloaded video", ArticlePostprocessor.validMedia(png, "video"))
        val errorBodies = listOf(
            "<!doctype html><html><body>Access denied</body></html>",
            "<html><body><img src='preview.jpg'><video src='preview.mp4'></video></body></html>",
            "{\"error\":\"media unavailable\"}",
            "#EXTM3U\n#EXT-X-VERSION:3\npreview.ts\n",
            "preview.mp4",
        )
        errorBodies.forEach { body ->
            assertFalse("HTML/preview/error text is not an image", ArticlePostprocessor.validMedia(body.toByteArray(), "image"))
            assertFalse("HTML/playlist/error text is not downloaded video", ArticlePostprocessor.validMedia(body.toByteArray(), "video"))
        }
        assertFalse(ArticlePostprocessor.validMedia(byteArrayOf(), "image"))
        assertFalse(ArticlePostprocessor.validMedia(byteArrayOf(), "video"))
        assertFalse("Truncated MP4 header is not complete media", ArticlePostprocessor.validMedia(byteArrayOf(0, 0, 0, 24) + "ftyp".toByteArray(), "video"))
    }
}
