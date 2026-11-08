package jp.fujimi.newsbunko.next.store

import jp.fujimi.newsbunko.next.daily.StoredMedia
import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import javax.imageio.ImageIO

class ArticleMediaWireTest {
    @TempDir lateinit var root: Path

    @Test fun dailyAndBookmarkListAndDetailUrlsAllResolveToDecodableOriginalPng() {
        val output = ByteArrayOutputStream()
        ImageIO.write(BufferedImage(2, 3, BufferedImage.TYPE_INT_RGB), "png", output)
        val png = output.toByteArray()
        val file = "写真 #100% cover.png"
        val saved = ArticleStore(root).create(JSONObject().put("title", "画像を含む記事").put("url", "https://example.test/image")
            .put("paragraphs", JSONArray(listOf("検証用本文。"))).put("image_paths", JSONArray(listOf("media/$file"))),
            "2026-11-05", listOf(StoredMedia("media/$file", png, "image")))
        val id = saved.metadata.getLong("id")
        ArticleStore(root).setBookmarked(id, true)
        val api = LocalLibraryApi(root)
        val daily = JSONObject(api.request("GET", "/api/daily?date=2026-11-05").body).getJSONArray("articles").getJSONObject(0)
        val article = JSONObject(api.request("GET", "/api/articles/$id").body)
        val bookmarkList = JSONArray(api.request("GET", "/api/bookmarks").body).getJSONObject(0)
        val bookmark = JSONObject(api.request("GET", "/api/bookmarks/$id").body)
        for ((item, context) in listOf(daily to false, article to false, bookmarkList to true, bookmark to true)) {
            val value = item.getJSONArray("image_paths").getString(0)
            assertTrue(value.startsWith("/api/${if (context) "bookmarks" else "articles"}/$id/media/"), value)
            val uri = URI(value)
            assertNull(uri.fragment)
            assertTrue(uri.rawPath.contains("%20") && uri.rawPath.contains("%23") && uri.rawPath.contains("%25"))
            val name = uri.path.substringAfter("/media/")
            assertEquals(file, name)
            val resolved = ArticleMediaAccess(root).resolve(id, name, context)
            assertArrayEquals(png, Files.readAllBytes(resolved))
            val decoded = ImageIO.read(resolved.toFile())
            assertNotNull(decoded)
            assertEquals(2, decoded.width)
            assertEquals(3, decoded.height)
        }
    }

    @Test fun unrelatedBrokenDayCannotPreventVerifiedTargetImageFromDecoding() {
        val output = ByteArrayOutputStream()
        ImageIO.write(BufferedImage(2, 3, BufferedImage.TYPE_INT_RGB), "png", output)
        val png = output.toByteArray()
        val target = ArticleStore(root).create(JSONObject().put("title", "有効な画像記事").put("url", "https://example.test/target")
            .put("paragraphs", JSONArray(listOf("有効な本文。"))).put("image_paths", JSONArray(listOf("media/photo.png"))),
            "2026-11-04", listOf(StoredMedia("media/photo.png", png, "image")))
        val unrelated = ArticleStore(root).create(JSONObject().put("title", "別の日の記事").put("url", "https://example.test/unrelated")
            .put("paragraphs", JSONArray(listOf("元の本文。"))), "2026-11-03")
        ArticleStore(root).setBookmarked(target.metadata.getLong("id"), true)
        Files.writeString(root.resolve(unrelated.directory).resolve("original.txt"), "外部変更された本文。")
        val api = LocalLibraryApi(root)
        val targetDay = api.request("GET", "/api/daily?date=2026-11-04")
        assertEquals(200, targetDay.status)
        val id = target.metadata.getLong("id")
        val image = ArticleMediaAccess(root).resolve(id, "photo.png")
        assertArrayEquals(png, Files.readAllBytes(image))
        assertEquals(2, ImageIO.read(image.toFile()).width)
        assertEquals(200, api.request("GET", "/api/articles/$id").status)
        val bookmarkList = api.request("GET", "/api/bookmarks")
        assertEquals(200, bookmarkList.status)
        assertEquals(id, JSONArray(bookmarkList.body).getJSONObject(0).getLong("id"))
        val bookmarkImage = ArticleMediaAccess(root).resolve(id, "photo.png", true)
        assertEquals(2, ImageIO.read(bookmarkImage.toFile()).width)
        assertEquals(200, api.request("GET", "/api/bookmarks/$id").status)
        assertEquals(409, api.request("GET", "/api/articles/${unrelated.metadata.getLong("id")}").status)

        val original = Files.readAllBytes(root.resolve(target.directory).resolve("original.txt"))
        Files.writeString(root.resolve(target.directory).resolve("original.txt"), "対象の本文も変更")
        assertThrows(ArticleFormatException::class.java) { ArticleMediaAccess(root).resolve(id, "photo.png") }
        Files.write(root.resolve(target.directory).resolve("original.txt"), original)
        val otherManifest = root.resolve(unrelated.directory).resolve("article.json")
        val duplicate = SyncFiles.json(otherManifest)
        duplicate.getJSONObject("article").put("id", id)
        SyncFiles.writeJson(otherManifest, duplicate)
        val failure = assertThrows(ArticleFormatException::class.java) { ArticleMediaAccess(root).resolve(id, "photo.png") }
        assertTrue(failure.message.orEmpty().contains("相同 ID"))
    }
}
