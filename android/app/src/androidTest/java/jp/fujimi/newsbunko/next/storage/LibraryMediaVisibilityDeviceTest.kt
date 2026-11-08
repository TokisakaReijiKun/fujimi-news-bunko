package jp.fujimi.newsbunko.next.storage

import android.content.Context
import android.graphics.Bitmap
import android.media.MediaScannerConnection
import android.os.Environment
import android.provider.MediaStore
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class LibraryMediaVisibilityDeviceTest {
    @Test fun markerProtectsExistingLibraryWithoutChangingItsFiles() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val root = Files.createTempDirectory(context.cacheDir.toPath(), "media-exclusion-").toFile()
        try {
            val media = File(root, "articles/fixture/media/image.png").also { it.parentFile!!.mkdirs() }
            media.writeBytes(byteArrayOf(1, 2, 3, 4))
            val expected = media.readBytes()
            assertTrue(LibraryMediaVisibility.ensureMarker(root))
            assertFalse(LibraryMediaVisibility.ensureMarker(root))
            assertTrue(File(root, MediaStore.MEDIA_IGNORE_FILENAME).isFile)
            assertArrayEquals(expected, media.readBytes())
        } finally {
            root.deleteRecursively()
        }
    }

    @Suppress("DEPRECATION")
    @Test fun rescanningHidesPreviouslyIndexedImageAndPreservesOriginalBytes() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        assertTrue("测试需要已授予公共文庫访问权限", DataDirectory.hasAccess(context))
        // This is a fresh synthetic directory outside the user's actual library.
        val root = Files.createTempDirectory(Environment.getExternalStorageDirectory().toPath(), "Fujimi-media-test-").toFile()
        val picture = File(root, "books/fixture/resources/image.png").also { it.parentFile!!.mkdirs() }
        try {
            val bitmap = Bitmap.createBitmap(4, 4, Bitmap.Config.ARGB_8888)
            try { picture.outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) } }
            finally { bitmap.recycle() }
            val expected = MessageDigest.getInstance("SHA-256").digest(picture.readBytes())
            val firstScan = CountDownLatch(1)
            MediaScannerConnection.scanFile(context, arrayOf(picture.absolutePath), null) { _, _ -> firstScan.countDown() }
            assertTrue("首次媒体扫描未完成", firstScan.await(30, TimeUnit.SECONDS))
            assertEquals("测试图片必须先真实进入系统相册索引", 1, indexedImages(context, picture))

            LibraryMediaVisibility.ensureMarker(root)
            val refreshed = CountDownLatch(1)
            LibraryMediaVisibility.refreshExistingMedia(context, root) { refreshed.countDown() }
            assertTrue("媒体索引刷新未完成", refreshed.await(30, TimeUnit.SECONDS))
            assertEquals("已有文庫图片应退出系统相册索引", 0, indexedImages(context, picture))
            assertTrue(picture.isFile)
            assertArrayEquals(expected, MessageDigest.getInstance("SHA-256").digest(picture.readBytes()))
        } finally {
            root.deleteRecursively()
            // Only the test's already removed synthetic file is reconciled here.
            MediaScannerConnection.scanFile(context, arrayOf(picture.absolutePath), null, null)
        }
    }

    @Suppress("DEPRECATION")
    private fun indexedImages(context: Context, picture: File): Int = context.contentResolver.query(
        MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
        arrayOf(MediaStore.Images.Media._ID),
        "${MediaStore.Images.Media.DATA} = ?",
        arrayOf(picture.absolutePath),
        null
    )!!.use { it.count }
}
