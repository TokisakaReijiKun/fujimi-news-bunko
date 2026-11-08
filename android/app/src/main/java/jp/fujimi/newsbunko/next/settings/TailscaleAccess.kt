package jp.fujimi.newsbunko.next.settings

import android.app.Activity
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.net.URI
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Runs on the sync executor; Android lifecycle notifications release the pending request. */
class TailscaleAccess(
    private val activity: Activity,
    private val connected: () -> Boolean = { hasTailscaleAddress(activity) },
    private val openClient: (() -> Unit)? = null,
    private val connectionWaitMs: Long = 15000
) {
    private class Request {
        val returned = CountDownLatch(1)
        val failure = AtomicReference<Exception?>()
        var away = false
    }
    private val main = Handler(Looper.getMainLooper())
    private var pending: Request? = null

    fun awaitReady(endpoint: String, active: () -> Boolean, waiting: () -> Unit) {
        val host = URI(PcEndpoint.normalize(endpoint)).host.split('.')
        if (host[0] != "100" || host[1].toInt() !in 64..127 || connected()) return
        val request = Request()
        waiting()
        main.post {
            if (!active()) { request.returned.countDown(); return@post }
            pending = request
            try {
                if (openClient != null) openClient.invoke() else {
                    val intent = activity.packageManager.getLaunchIntentForPackage("com.tailscale.ipn")
                        ?: error("Tailscaleがインストールされていません。")
                    // Official Tailscale automation action. Login and VPN consent remain in its UI.
                    activity.sendBroadcast(Intent("com.tailscale.ipn.CONNECT_VPN").setPackage("com.tailscale.ipn"))
                    activity.startActivity(intent)
                }
            } catch (failure: Exception) {
                request.failure.set(IllegalStateException(failure.message ?: "Tailscaleを開けませんでした。"))
                request.returned.countDown()
            }
        }
        try {
            val returnDeadline = SystemClock.elapsedRealtime() + TimeUnit.MINUTES.toMillis(5)
            while (!request.returned.await(250, TimeUnit.MILLISECONDS)) {
                check(active()) { "接続を中止しました。" }
                check(SystemClock.elapsedRealtime() < returnDeadline) { "Tailscaleで接続してから、もう一度お試しください。" }
            }
            check(active()) { "接続を中止しました。" }
            request.failure.get()?.let { throw it }
            val deadline = SystemClock.elapsedRealtime() + connectionWaitMs
            while (!connected() && SystemClock.elapsedRealtime() < deadline) {
                check(active()) { "接続を中止しました。" }
                Thread.sleep(250)
            }
            check(connected()) { "TailscaleにログインしてVPN接続を許可してください。" }
        } finally {
            main.post { if (pending === request) pending = null }
        }
    }

    fun onPause() { pending?.away = true }
    fun onResume() { pending?.takeIf { it.away }?.returned?.countDown() }
    fun cancel() { main.post { pending?.returned?.countDown(); pending = null } }

    companion object {
        private fun hasTailscaleAddress(activity: Activity): Boolean = try {
            val manager = activity.getSystemService(ConnectivityManager::class.java)
            manager.allNetworks.any { network ->
                manager.getNetworkCapabilities(network)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true &&
                manager.getLinkProperties(network)?.linkAddresses?.any {
                    val bytes = it.address.address
                    bytes.size == 4 && bytes[0].toInt() == 100 && (bytes[1].toInt() and 255) in 64..127
                } == true
            }
        } catch (_: Exception) { false }
    }
}
