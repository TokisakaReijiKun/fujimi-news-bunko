package jp.fujimi.newsbunko.next

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.res.Configuration
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.WindowInsets
import android.view.View
import android.view.WindowInsetsController
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

class MainActivity : Activity() {
    lateinit var webView: WebView
        private set
    lateinit var bridge: MobileBridge
        private set
    private var chooser: ValueCallback<Array<Uri>>? = null

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        webView = WebView(this)
        WebView.setWebContentsDebuggingEnabled(applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0)
        val container = FrameLayout(this)
        container.addView(webView, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        val dark = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
        container.setBackgroundColor(if (dark) Color.rgb(24, 30, 27) else Color.rgb(244, 245, 240))
        setContentView(container)
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.TRANSPARENT
        if (Build.VERSION.SDK_INT >= 30) window.setDecorFitsSystemWindows(false)
        if (Build.VERSION.SDK_INT >= 30) {
            val mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            window.insetsController?.setSystemBarsAppearance(if (dark) 0 else mask, mask)
        } else {
            window.decorView.systemUiVisibility = if (dark) 0 else View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        }
        // WebView does not reliably inset fixed HTML elements with its own padding.
        // Inset the native parent so the page viewport clears OS bars and the keyboard.
        container.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                val keyboard = insets.getInsets(WindowInsets.Type.ime())
                view.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, keyboard.bottom))
            } else {
                view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
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
                val response = loader.shouldInterceptRequest(request.url)
                if (response?.mimeType == "text/html") {
                    response.responseHeaders = mapOf("Content-Security-Policy" to
                        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; media-src 'self' https: blob:; connect-src 'self' https:; font-src 'self' data:; frame-src 'none'; object-src 'none'; base-uri 'none'")
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
        if (::webView.isInitialized) webView.evaluateJavascript("window.__fujimiRefreshNativeSettings?.()", null)
    }

    override fun onSaveInstanceState(state: Bundle) {
        webView.saveState(state)
        super.onSaveInstanceState(state)
    }

    override fun onDestroy() {
        chooser?.onReceiveValue(null)
        chooser = null
        bridge.close()
        webView.removeJavascriptInterface("FujimiMobile")
        webView.stopLoading()
        webView.destroy()
        super.onDestroy()
    }
}
