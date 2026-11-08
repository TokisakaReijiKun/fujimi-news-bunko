package jp.fujimi.newsbunko.next

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import jp.fujimi.newsbunko.next.settings.TailscaleAccess
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

@RunWith(AndroidJUnit4::class)
class TailscaleAccessDeviceTest {
    @Test fun lanAndConnectedTailscaleDoNotLaunchAnotherApp() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            lateinit var access: TailscaleAccess
            val connected = AtomicBoolean(false)
            scenario.onActivity { access = TailscaleAccess(it, connected::get, { fail("不应打开客户端") }) }
            access.awaitReady("http://192.168.1.20:8429", { true }, { fail("不应等待") })
            connected.set(true)
            access.awaitReady("http://100.69.147.24:8429", { true }, { fail("不应等待") })
        }
    }

    @Test fun disconnectedTailscaleLaunchesOnceAndContinuesAfterReturning() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            val connected = AtomicBoolean(false)
            val opened = CountDownLatch(1)
            lateinit var access: TailscaleAccess
            scenario.onActivity { access = TailscaleAccess(it, connected::get, { opened.countDown() }) }
            val executor = Executors.newSingleThreadExecutor()
            try {
                val result = executor.submit { access.awaitReady("http://100.69.147.24:8429", { true }, {}) }
                assertTrue(opened.await(5, TimeUnit.SECONDS))
                scenario.onActivity { access.onResume() }
                assertFalse("必须先离开文库，避免扫码返回时提前继续", result.isDone)
                scenario.onActivity { access.onPause() }
                connected.set(true)
                scenario.onActivity { access.onResume() }
                result.get(5, TimeUnit.SECONDS)
            } finally { executor.shutdownNow() }
        }
    }

    @Test fun missingClientAndUnfinishedVpnNeverReportReady() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            lateinit var access: TailscaleAccess
            scenario.onActivity { access = TailscaleAccess(it, { false }, { error("Tailscaleがインストールされていません。") }) }
            try {
                access.awaitReady("http://100.69.147.24:8429", { true }, {})
                fail("未安装不能继续配对")
            } catch (failure: IllegalStateException) { assertTrue(failure.message!!.contains("インストール")) }
            val opened = CountDownLatch(1)
            scenario.onActivity { access = TailscaleAccess(it, { false }, { opened.countDown() }, 1) }
            val executor = Executors.newSingleThreadExecutor()
            try {
                val result = executor.submit<String> {
                    try { access.awaitReady("http://100.69.147.24:8429", { true }, {}); "unexpected ready" }
                    catch (failure: IllegalStateException) { failure.message.orEmpty() }
                }
                assertTrue(opened.await(5, TimeUnit.SECONDS))
                scenario.onActivity { access.onPause(); access.onResume() }
                assertTrue(result.get(5, TimeUnit.SECONDS).contains("VPN"))
            } finally { executor.shutdownNow() }
        }
    }
}
