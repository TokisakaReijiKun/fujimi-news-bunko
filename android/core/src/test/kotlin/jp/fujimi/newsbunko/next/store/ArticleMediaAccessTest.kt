package jp.fujimi.newsbunko.next.store

import jp.fujimi.newsbunko.next.daily.StoredMedia
import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.net.URI

class ArticleMediaAccessTest {
    @TempDir lateinit var data: Path

    @Test fun servesOnlyTheExactRegisteredArticleMediaAndLocalApiUsesItsArticleRoute() {
        val saved = create("一篇目")
        val id = saved.metadata.getLong("id")
        val path = ArticleMediaAccess(data).resolve(id, "本文画像.jpg")
        assertEquals(data.resolve(saved.directory).resolve("media/本文画像.jpg"), path)
        assertArrayEquals(bytes, Files.readAllBytes(path))
        val response = LocalLibraryApi(data).request("GET", "/api/articles/$id")
        assertEquals(200, response.status)
        val wire = JSONObject(response.body)
        assertEquals("/api/articles/$id/media/本文画像.jpg", URI(wire.getJSONArray("image_paths").getString(0)).path)
        assertEquals("media/本文画像.jpg", ArticleReader(data).load(saved.directory).metadata.getJSONArray("image_paths").getString(0))
    }

    @Test fun sameLengthTamperingFailsHashValidation() {
        val saved = create("改変")
        Files.write(data.resolve(saved.directory).resolve("media/本文画像.jpg"), byteArrayOf(9, 2, 3, 4))
        val error = assertThrows(IllegalArgumentException::class.java) {
            ArticleMediaAccess(data).resolve(saved.metadata.getLong("id"), "本文画像.jpg")
        }
        assertTrue(error.message.orEmpty().contains("校验"))
    }

    @Test fun changedSizeAndMissingFileAreBothRejected() {
        val saved = create("サイズ")
        val media = data.resolve(saved.directory).resolve("media/本文画像.jpg")
        Files.write(media, byteArrayOf(1, 2))
        assertThrows(IllegalArgumentException::class.java) {
            ArticleMediaAccess(data).resolve(saved.metadata.getLong("id"), "本文画像.jpg")
        }
        Files.delete(media)
        assertThrows(IllegalArgumentException::class.java) {
            ArticleMediaAccess(data).resolve(saved.metadata.getLong("id"), "本文画像.jpg")
        }
    }

    @Test fun rejectsUnregisteredExistingFilesAndOtherArticlesAttachments() {
        val first = create("最初")
        val second = create("次", withMedia = false)
        val folder = data.resolve(second.directory).resolve("media")
        Files.write(folder.resolve("本文画像.jpg"), bytes)
        assertThrows(NoSuchElementException::class.java) {
            ArticleMediaAccess(data).resolve(second.metadata.getLong("id"), "本文画像.jpg")
        }
        assertThrows(NoSuchElementException::class.java) {
            ArticleMediaAccess(data).resolve(first.metadata.getLong("id"), "未登録.jpg")
        }
    }

    @Test fun traversalCannotExposeArticleTextOrAFileOutsideTheArticle() {
        val saved = create("安全")
        val id = saved.metadata.getLong("id")
        val outside = data.resolve("diagnostics/secret.txt")
        Files.writeString(outside, "not publicly accessible")
        for (name in listOf("../original.txt", "../../../../diagnostics/secret.txt", "/original.txt", "..\\original.txt")) {
            assertThrows(Exception::class.java) { ArticleMediaAccess(data).resolve(id, name) }
        }
        assertEquals("not publicly accessible", Files.readString(outside))
    }

    @Test fun tamperedManifestCannotGrantPathTraversalEvenIfTheRequestedNameIsRegistered() {
        val saved = create("偽登録")
        val manifestFile = data.resolve(saved.directory).resolve("article.json")
        val manifest = JSONObject(Files.readString(manifestFile))
        val asset = manifest.getJSONArray("assets").getJSONObject(0)
        asset.put("path", "media/../original.txt")
        manifest.getJSONObject("article").put("image_paths", JSONArray(listOf("media/../original.txt")))
        Files.writeString(manifestFile, manifest.toString())
        assertThrows(IllegalArgumentException::class.java) {
            ArticleMediaAccess(data).resolve(saved.metadata.getLong("id"), "../original.txt")
        }
    }

    @Test fun articleTextMustStillMatchItsManifestBeforeAnyAttachmentCanBeServed() {
        val saved = create("原文校验")
        Files.writeString(data.resolve(saved.directory).resolve("original.txt"), "外部修改正文")
        assertThrows(ArticleFormatException::class.java) {
            ArticleMediaAccess(data).resolve(saved.metadata.getLong("id"), "本文画像.jpg")
        }
    }

    @Test fun wireEncodesEachLocalMediaPathSegmentWithoutChangingStoredFileNamesOrRemotePreviewUrls() {
        val imageName = "media/日本の図 #100% cover.jpg"
        val videoName = "media/sub dir/映像 #25%.mp4"
        val remote = "https://example.test/player?clip=1#preview"
        val metadata = JSONObject().put("title", "URL安全性").put("url", "https://example.test/encoding")
            .put("paragraphs", JSONArray(listOf("本文。"))).put("image_paths", JSONArray(listOf(imageName)))
            .put("video_urls", JSONArray(listOf(videoName, remote)))
        val saved = ArticleStore(data).create(metadata, "2026-10-01", listOf(
            StoredMedia(imageName, bytes, "image"), StoredMedia(videoName, bytes, "video")))
        val id = saved.metadata.getLong("id")
        val response = LocalLibraryApi(data).request("GET", "/api/articles/$id")
        assertEquals(200, response.status)
        val wire = JSONObject(response.body)
        val imageUrl = wire.getJSONArray("image_paths").getString(0)
        val videoUrl = wire.getJSONArray("video_urls").getString(0)
        assertFalse(imageUrl.contains(' '))
        assertTrue(imageUrl.contains("%23") && imageUrl.contains("%25") && imageUrl.contains("%20"))
        assertEquals(null, URI(imageUrl).fragment)
        assertEquals("/api/articles/$id/media/日本の図 #100% cover.jpg", URI(imageUrl).path)
        assertEquals("/api/articles/$id/media/sub dir/映像 #25%.mp4", URI(videoUrl).path)
        assertEquals(remote, wire.getJSONArray("video_urls").getString(1))
        assertEquals(imageName, ArticleReader(data).load(saved.directory).metadata.getJSONArray("image_paths").getString(0))
        assertArrayEquals(bytes, Files.readAllBytes(ArticleMediaAccess(data).resolve(id, URI(imageUrl).path.substringAfter("/media/"))))
    }

    @Test fun wireNeverEnablesInstantPlaybackForAnExplicitlySilentSource() {
        val metadata = JSONObject().put("title", "无朗读").put("url", "https://example.test/silent")
            .put("paragraphs", JSONArray(listOf("本文。"))).put("source_voice_mode", "none")
            .put("voice_mode", "none").put("audio_voice_mode", "none").put("audio_status", "disabled").put("audio_path", "")
        val saved = ArticleStore(data).create(metadata, "2026-10-01")
        val response = LocalLibraryApi(data).request("GET", "/api/articles/${saved.metadata.getLong("id")}")
        assertEquals(200, response.status)
        val wire = JSONObject(response.body)
        assertEquals("none", wire.getString("voice_mode"))
        assertEquals("none", wire.getString("audio_voice_mode"))
        assertEquals("disabled", wire.getString("audio_status"))
        assertEquals("", wire.getString("audio_path"))
    }

    private fun create(title: String, withMedia: Boolean = true): ArticleSnapshot {
        val article = JSONObject().put("title", title).put("url", "https://example.test/$title")
            .put("source_name", "NHKニュース").put("paragraphs", JSONArray(listOf("公開本文です。")))
            .put("image_paths", JSONArray(if (withMedia) listOf("media/本文画像.jpg") else emptyList<String>()))
        val media = if (withMedia) listOf(StoredMedia("media/本文画像.jpg", bytes, "image")) else emptyList()
        return ArticleStore(data).create(article, "2026-10-01", media)
    }

    private val bytes = byteArrayOf(1, 2, 3, 4)
}
