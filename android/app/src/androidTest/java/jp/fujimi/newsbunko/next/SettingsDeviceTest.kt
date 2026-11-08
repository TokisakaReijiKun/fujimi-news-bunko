package jp.fujimi.newsbunko.next

import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import android.content.Context
import jp.fujimi.newsbunko.next.settings.SecretStore
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class SettingsDeviceTest {
    @Test fun keystorePersistsCiphertextAndClearsSecret() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val secret = "test-only-device-secret-123456"
        val store = SecretStore(context)
        try {
            assertTrue(store.saveDeepSeekKey(secret))
            assertEquals(secret, SecretStore(context).readDeepSeekKey())
            val persisted = context.getSharedPreferences("protected-secrets", Context.MODE_PRIVATE).all
            assertFalse(persisted.values.any { it.toString().contains(secret) })
            assertFalse(store.saveDeepSeekKey("bad"))
            assertEquals(secret, store.readDeepSeekKey())
            assertTrue(store.clearDeepSeekKey())
            assertFalse(store.isConfigured())
        } finally { store.clearDeepSeekKey() }
    }

    @Test fun settingsPagePersistsLibraryChoiceAcrossActivityRecreation() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            assertTrue(waitFor(scenario, "typeof window.api === 'function'"))
            evaluate(scenario, "window.__deviceSave = null; api('/api/settings/library',{method:'PUT',body:JSON.stringify({sort:'series',lookup_chinese_translations:false})}).then(()=>window.__deviceSave=true).catch(()=>window.__deviceSave=false);true")
            assertTrue(waitFor(scenario, "window.__deviceSave === true"))
            scenario.recreate()
            assertTrue(waitFor(scenario, "typeof window.api === 'function'"))
            evaluate(scenario, "window.__deviceLoad=null;api('/api/settings/library').then(v=>window.__deviceLoad=v);true")
            assertTrue(waitFor(scenario, "window.__deviceLoad?.sort === 'series' && window.__deviceLoad?.lookup_chinese_translations === false"))
            evaluate(scenario, "showView('settings');true")
            val version = ApplicationProvider.getApplicationContext<Context>().let { it.packageManager.getPackageInfo(it.packageName, 0).versionName }
            assertTrue(waitFor(scenario, "document.querySelector('#mobile-app-version').textContent === '$version'"))
            assertEquals("true", evaluate(scenario, "!document.querySelector('#mobile-app-settings-panel').hidden"))
            assertTrue(waitFor(scenario, "document.querySelector('#voice-list')?.children.length > 0"))
            assertEquals("true", evaluate(scenario, "document.querySelector('#voice-error').hidden"))
            evaluate(scenario, "window.__edgeVoices=null;api('/api/browser-voices').then(v=>window.__edgeVoices=JSON.stringify(v.map(x=>x.id)));true")
            assertTrue(waitFor(scenario, "window.__edgeVoices === '[\"ja-JP-KeitaNeural\",\"ja-JP-NanamiNeural\"]'"))
            assertEquals("true", evaluate(scenario, "document.querySelector('#mobile-sync-now').disabled"))
            assertEquals("false", evaluate(scenario, "document.querySelector('#daily-mode [data-mode=automatic]').disabled"))
            assertTrue(waitFor(scenario, "!document.querySelector('#generate-daily').disabled"))
        }
    }

    @Test fun automaticModePersistsARealFutureAlarmAndManualModeCancelsIt() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val preferences = context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE)
        val scheduler = jp.fujimi.newsbunko.next.daily.DailyRuntime.get(context).schedule
        val time = java.time.LocalTime.now(jp.fujimi.newsbunko.next.settings.CstSchedule.zone)
            .plusHours(2).format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                assertTrue(waitFor(scenario, "typeof window.api === 'function'"))
                evaluate(scenario, "window.__scheduleSave=null;api('/api/settings/daily-schedule',{method:'PUT',body:JSON.stringify({mode:'automatic',time:'$time'})}).then(v=>window.__scheduleSave=v);true")
                assertTrue(waitFor(scenario, "window.__scheduleSave?.mode === 'automatic' && Boolean(window.__scheduleSave?.next_run)"))
                assertTrue(preferences.getLong("next-alarm", 0) > System.currentTimeMillis())
                scenario.recreate()
                assertTrue(waitFor(scenario, "typeof window.api === 'function'"))
                evaluate(scenario, "showView('settings');true")
                assertTrue(waitFor(scenario, "document.querySelector('#daily-mode [data-mode=automatic]').classList.contains('active')"))
                assertEquals("\"$time\"", evaluate(scenario, "document.querySelector('#daily-update-time').value"))
                evaluate(scenario, "document.querySelector('#daily-mode [data-mode=manual]').click();true")
                assertTrue(waitFor(scenario, "document.querySelector('#daily-mode [data-mode=manual]').classList.contains('active') && document.querySelector('#daily-update-time').disabled"))
                evaluate(scenario, "window.__manualSaved=false;api('/api/settings/daily-schedule').then(v=>window.__manualSaved=v.mode==='manual');true")
                assertTrue(waitFor(scenario, "window.__manualSaved === true"))
            }
            assertEquals(0L, preferences.getLong("next-alarm", 0))
        } finally { scheduler.configure("manual", "00:00") }
    }

    @Test fun clearingPCAddressDoesNotStartSync() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertTrue(activity.bridge.setServerUrl("https://192.168.1.20:8429"))
                assertEquals("offline", JSONObject(activity.bridge.mobileStatus()).getString("windows_status"))
                assertEquals("unavailable", JSONObject(activity.bridge.mobileStatus()).getString("sync_state"))
                assertFalse(activity.bridge.setServerUrl("https://8.8.8.8"))
                assertTrue(activity.bridge.setServerUrl(""))
                assertEquals("unconfigured", JSONObject(activity.bridge.mobileStatus()).getString("windows_status"))
            }
        }
    }

    private fun evaluate(scenario: ActivityScenario<MainActivity>, script: String): String {
        val done = CountDownLatch(1)
        var result = ""
        scenario.onActivity { it.webView.evaluateJavascript(script) { value -> result = value; done.countDown() } }
        assertTrue("WebView callback timed out", done.await(10, TimeUnit.SECONDS))
        return result
    }

    private fun waitFor(scenario: ActivityScenario<MainActivity>, condition: String): Boolean {
        val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(30)
        while (System.nanoTime() < until) {
            if (evaluate(scenario, "Boolean($condition)") == "true") return true
            Thread.sleep(150)
        }
        return false
    }
}
