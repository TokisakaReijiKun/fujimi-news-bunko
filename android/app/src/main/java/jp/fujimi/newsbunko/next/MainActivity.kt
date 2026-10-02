package jp.fujimi.newsbunko.next

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.res.Configuration
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.WindowInsetsController
import android.view.View
import android.widget.FrameLayout
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.webkit.WebViewAssetLoader
import jp.fujimi.newsbunko.next.bridge.MobileBridge
import jp.fujimi.newsbunko.next.daily.DailyRuntime
import jp.fujimi.newsbunko.next.store.ArticleMediaAccess
import jp.fujimi.newsbunko.next.storage.DataDirectory
import jp.fujimi.newsbunko.next.speech.ArticleAudioResponse
import java.io.FileInputStream

class MainActivity : Activity() {
    lateinit var webView: WebView
        private set
    lateinit var bridge: MobileBridge
        private set
    private var chooser: ValueCallback<Array<Uri>>? = null
    private var initialState: Bundle? = null
    private var storagePromptVisible = false

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        initialState = state
    }

    private fun openLibrary(state: Bundle?) {
        DataDirectory.prepare(this)
        webView = WebView(this)
        WebView.setWebContentsDebuggingEnabled(applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0)
        val container = FrameLayout(this)
        container.addView(webView, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        val dark = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
        container.setBackgroundColor(if (dark) Color.rgb(24, 30, 27) else Color.rgb(244, 245, 240))
        setContentView(container)
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.TRANSPARENT
        if (Build.VERSION.SDK_INT >= 29) {
            window.isNavigationBarContrastEnforced = false
            window.isStatusBarContrastEnforced = false
        }
        if (Build.VERSION.SDK_INT >= 30) {
            // The original APK renders its WebView edge-to-edge.  The drawer then
            // paints through the status/navigation areas instead of exposing the
            // activity's light background as two white bands.  Keep status icons
            // dark on the paper page, while the navigation gesture bar remains
            // light over the dark drawer just like the original.
            window.setDecorFitsSystemWindows(false)
            val mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
            window.insetsController?.setSystemBarsAppearance(if (dark) 0 else mask, mask)
        } else {
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                (if (dark) 0 else View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR)
        }
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            // A requested read may start after synthesis or metadata finishes.
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            javaScriptCanOpenWindowsAutomatically = false
            textZoom = (resources.configuration.fontScale * 100).toInt().coerceIn(100, 200)
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false)
        val loader = WebViewAssetLoader.Builder().addPathHandler("/", WebViewAssetLoader.AssetsPathHandler(this)).build()
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                if (trusted(request.url) && request.url.path?.startsWith("/api/articles/") == true) {
                    val audio = Regex("^/api/articles/(\\d+)/assets/audio/(.+)$").matchEntire(request.url.path.orEmpty())
                    if (audio != null) {
                        return try {
                            ArticleAudioResponse(DataDirectory.root().toPath()).open(audio.groupValues[1].toLong(), audio.groupValues[2],
                                request.requestHeaders.entries.firstOrNull { it.key.equals("Range", true) }?.value)
                        } catch (_: Exception) {
                            WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", emptyMap(), "完整音频缺失或正文校验失败。".byteInputStream())
                        }
                    }
                    val media = Regex("^/api/articles/(\\d+)/media/(.+)$").matchEntire(request.url.path.orEmpty())
                    if (media != null) {
                        return try {
                            val path = ArticleMediaAccess(DataDirectory.root().toPath()).resolve(media.groupValues[1].toLong(), media.groupValues[2])
                            val extension = path.fileName.toString().substringAfterLast('.', "").lowercase()
                            val type = mapOf("jpg" to "image/jpeg", "jpeg" to "image/jpeg", "png" to "image/png", "webp" to "image/webp", "gif" to "image/gif", "mp4" to "video/mp4", "m4v" to "video/mp4")[extension] ?: "application/octet-stream"
                            WebResourceResponse(type, null, FileInputStream(path.toFile())).apply { responseHeaders = mapOf("X-Content-Type-Options" to "nosniff", "Cache-Control" to "no-store") }
                        } catch (_: Exception) {
                            WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", emptyMap(), "媒体缺失或校验失败。".byteInputStream())
                        }
                    }
                }
                val response = loader.shouldInterceptRequest(request.url)
                if (response?.mimeType == "text/html") {
                    response.responseHeaders = mapOf("Content-Security-Policy" to
                        "default-src 'self'; script-src 'self' 'unsafe-inline' https://news.web.nhk; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; media-src 'self' https: blob:; connect-src 'self' https:; font-src 'self' data:; frame-src 'none'; object-src 'none'; base-uri 'none'")
                }
                return response
            }
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (trusted(request.url)) return false
                if (request.isForMainFrame && request.url.scheme in setOf("https", "http")) {
                    try { startActivity(Intent(Intent.ACTION_VIEW, request.url)) } catch (_: ActivityNotFoundException) { }
                }
                return true
            }
            override fun onPageFinished(view: WebView, url: String) {
                if (!trusted(Uri.parse(url))) {
                    view.removeJavascriptInterface("FujimiMobile")
                    view.loadUrl("about:blank")
                }
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                chooser?.onReceiveValue(null)
                chooser = callback
                return try { startActivityForResult(params.createIntent(), 1001); true }
                catch (_: ActivityNotFoundException) { chooser = null; callback.onReceiveValue(null); false }
            }
        }
        bridge = MobileBridge(this, webView)
        webView.addJavascriptInterface(bridge, "FujimiMobile")
        if (state == null || webView.restoreState(state) == null) {
            webView.loadUrl("https://${WebViewAssetLoader.DEFAULT_DOMAIN}/static/index.html#daily")
        }
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT) { handleBack() }
        }
    }

    private fun trusted(uri: Uri) = uri.scheme == "https" && uri.host == WebViewAssetLoader.DEFAULT_DOMAIN && uri.port == -1

    private fun handleBack() {
        if (!::webView.isInitialized) { finish(); return }
        webView.evaluateJavascript("Boolean(window.__fujimiHandleBack?.())") { handled ->
            if (handled != "true") {
                if (webView.canGoBack()) webView.goBack() else finish()
            }
        }
    }

    @Deprecated("Android 13 uses OnBackInvokedDispatcher")
    override fun onBackPressed() = handleBack()

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 1001) {
            chooser?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            chooser = null
        }
    }

    override fun onResume() {
        super.onResume()
        if (!DataDirectory.hasAccess(this)) {
            requestStorageAccess()
            return
        }
        if (!::webView.isInitialized) {
            try { openLibrary(initialState); initialState = null }
            catch (failure: Exception) {
                AlertDialog.Builder(this).setTitle("文庫无法打开")
                    .setMessage(failure.message ?: "请检查手机存储空间。")
                    .setPositiveButton("关闭") { _, _ -> finish() }.show()
                return
            }
        }
        try { DailyRuntime.get(applicationContext).schedule.reconcile() } catch (_: Exception) {
            getSharedPreferences("mobile-settings", MODE_PRIVATE).edit().putString("alarm-error", "日刊定时未能安排，请在设置页重新选择生成方式。").commit()
        }
        if (::webView.isInitialized) webView.evaluateJavascript("window.__fujimiRefreshNativeSettings?.()", null)
    }

    private fun requestStorageAccess() {
        if (storagePromptVisible || isFinishing) return
        storagePromptVisible = true
        AlertDialog.Builder(this).setTitle("允许保存文庫文件")
            .setMessage("文庫保存到 ${DataDirectory.root().absolutePath}。请在系统页面允许存储访问，然后返回 APP。")
            .setPositiveButton("去授权") { _, _ ->
                if (Build.VERSION.SDK_INT < 30) {
                    requestPermissions(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE), 1002)
                } else {
                    try {
                        startActivity(Intent(android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName")))
                    } catch (_: ActivityNotFoundException) {
                        startActivity(Intent(android.provider.Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                    }
                }
            }
            .setNegativeButton("取消") { _, _ -> finish() }
            .setOnDismissListener { storagePromptVisible = false }
            .show()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1002) {
            if (DataDirectory.hasAccess(this)) recreate() else finish()
        }
    }

    override fun onSaveInstanceState(state: Bundle) {
        if (::webView.isInitialized) webView.saveState(state)
        super.onSaveInstanceState(state)
    }

    override fun onDestroy() {
        chooser?.onReceiveValue(null)
        chooser = null
        if (::bridge.isInitialized) bridge.close()
        if (::webView.isInitialized) {
            webView.removeJavascriptInterface("FujimiMobile")
            webView.stopLoading()
            webView.destroy()
        }
        super.onDestroy()
    }
}
