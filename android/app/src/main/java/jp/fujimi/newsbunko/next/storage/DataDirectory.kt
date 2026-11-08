package jp.fujimi.newsbunko.next.storage

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Environment
import java.io.File

/** Shared PC-format library; credentials and packaged dictionary stay private. */
object DataDirectory {
    @Suppress("DEPRECATION")
    fun root(): File = File(Environment.getExternalStorageDirectory(), "富士見新聞文庫/data")

    fun hasAccess(context: Context): Boolean = if (Build.VERSION.SDK_INT >= 30) {
        Environment.isExternalStorageManager()
    } else {
        context.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
    }

    fun prepare(context: Context): File {
        check(hasAccess(context)) { "请先允许文庫访问手机存储。" }
        return root().also {
            check(it.isDirectory || it.mkdirs()) { "无法创建文庫目录：${it.absolutePath}，请检查存储空间。" }
            LibraryMediaVisibility.prepare(context, it)
        }
    }
}
