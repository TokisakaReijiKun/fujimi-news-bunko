package jp.fujimi.newsbunko.next.storage

import android.content.Context
import android.media.MediaScannerConnection
import android.provider.MediaStore
import android.util.Log
import android.webkit.MimeTypeMap
import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger

/** Keep this public document library out of gallery and music collections. */
internal object LibraryMediaVisibility {
    private val refreshing = mutableSetOf<String>()

    @Synchronized
    fun prepare(context: Context, root: File) {
        val created = ensureMarker(root)
        val preferences = context.getSharedPreferences("library-media-exclusion-v1", Context.MODE_PRIVATE)
        val key = root.absolutePath
        if (created) preferences.edit().remove(key).apply()
        if (preferences.getBoolean(key, false) || !refreshing.add(key)) return

        // Existing libraries may already have Gallery entries. A marker alone is
        // not enough: ask Android to reclassify their files without deleting data.
        Thread({
            try {
                refreshExistingMedia(context.applicationContext, root) {
                    preferences.edit().putBoolean(key, true).apply()
                    synchronized(this) { refreshing.remove(key) }
                }
            } catch (_: Exception) {
                synchronized(this) { refreshing.remove(key) }
                Log.w("LibraryMediaVisibility", "Media index refresh unavailable; will retry on the next library open.")
            }
        }, "fujimi-media-exclusion").start()
    }

    fun ensureMarker(root: File): Boolean {
        val marker = File(root, MediaStore.MEDIA_IGNORE_FILENAME)
        val created = marker.createNewFile()
        check(marker.isFile) { "无法保护文庫媒体，请检查存储访问权限。" }
        return created
    }

    fun refreshExistingMedia(context: Context, root: File, onComplete: () -> Unit) {
        val paths = Files.walk(root.toPath()).use { entries ->
            entries.filter { Files.isRegularFile(it, LinkOption.NOFOLLOW_LINKS) }
                .map { it.toFile() }
                .filter {
                    val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(it.extension.lowercase(Locale.ROOT))
                    mime?.startsWith("image/") == true || mime?.startsWith("video/") == true || mime?.startsWith("audio/") == true
                }
                .map { it.absolutePath }
                .toArray { size -> arrayOfNulls<String>(size) }
        }
        if (paths.isEmpty()) {
            onComplete()
            return
        }
        val remaining = AtomicInteger(paths.size)
        MediaScannerConnection.scanFile(context, paths, null) { _, _ ->
            // A hidden file can legitimately return a null URI (Android 10).
            // Completion means all rescan requests finished, not a Gallery UI guarantee.
            if (remaining.decrementAndGet() == 0) onComplete()
        }
    }
}
