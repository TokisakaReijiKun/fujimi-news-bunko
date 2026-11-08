package jp.fujimi.newsbunko.next

import android.os.Build
import android.os.Environment
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Read-only UI checks for a dedicated emulator; no synthesis, pairing, or library writes. */
@RunWith(AndroidJUnit4::class)
class RedesignDeviceTest {
    @Before fun requireIsolatedEmulator() {
        assumeTrue("Run these checks on the dedicated QA emulator only.",
            Build.HARDWARE.contains("ranchu") || Build.HARDWARE.contains("goldfish"))
        assertTrue("Grant public-library access on the QA emulator before running these checks.",
            Build.VERSION.SDK_INT < 30 || Environment.isExternalStorageManager())
    }

    @Test fun formalEntryMountsRedesignAndNavigatesAllMainViews() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            awaitReady(scenario)
            assertEquals("true", evaluate(scenario, "location.pathname === '/static/index.html'"))
            assertEquals("true", evaluate(scenario,
                "document.documentElement.dataset.redesignApp === 'true' && document.querySelectorAll('fujimi-app').length === 1"))
            assertEquals("The approved compact article opening must reach the APK.", "true", evaluate(scenario, """
                (() => {
                  const template = document.querySelector('#article-template').content;
                  return template.querySelector('.article-heading > .title')?.tagName === 'H1'
                    && !!template.querySelector('.article-utility')
                    && !template.querySelector('.article-top, .article-meta');
                })()
            """.trimIndent()))
            for (view in listOf("daily", "reader", "library", "dictionary", "settings", "bookmarks")) {
                navigate(scenario, view)
                assertEquals("Horizontal overflow in $view", "true", evaluate(scenario, """
                    (() => {
                      const main = document.querySelector('fujimi-app').shadowRoot.querySelector('.page-main');
                      return document.documentElement.scrollWidth <= innerWidth + 1
                        && (!main || main.scrollWidth <= main.clientWidth + 1);
                    })()
                """.trimIndent()))
            }
        }
    }

    @Test fun voicePreviewAndSelectionRemainSeparateAccessibleControls() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            awaitReady(scenario)
            navigate(scenario, "settings")
            assertEquals("true", evaluate(scenario, """
                (() => {
                  const root = document.querySelector('fujimi-app').shadowRoot;
                  const row = root.querySelector('.settings-voice');
                  const preview = row?.querySelector('.settings-voice-preview');
                  const select = row?.querySelector('.settings-voice-select');
                  return !!preview && !!select && preview !== select
                    && preview.tagName === 'BUTTON' && select.tagName === 'BUTTON'
                    && preview.parentElement === select.parentElement
                    && !preview.contains(select) && !select.contains(preview)
                    && !!preview.getAttribute('aria-label') && !!select.getAttribute('aria-label')
                    && !!preview.querySelector('.dictionary-sound-wave-inner')
                    && !!preview.querySelector('.dictionary-sound-wave-outer')
                    && !root.querySelector('.voice-reference-audio');
                })()
            """.trimIndent()))
            evaluate(scenario,
                "document.querySelector('fujimi-app').shadowRoot.querySelector('.settings-voice-select').click(); true")
            assertTrue("Voice selection did not open.", waitFor(scenario,
                "document.querySelector('fujimi-app').shadowRoot.querySelector('dialog')?.open === true"))
            assertEquals("true", evaluate(scenario,
                "!document.querySelector('fujimi-app').shadowRoot.querySelector('.voice-reference-audio')"))
            evaluate(scenario, "document.querySelector('fujimi-app').shadowRoot.querySelector('dialog').close(); true")
            assertTrue("Voice selection did not close.", waitFor(scenario,
                "document.querySelector('fujimi-app').shadowRoot.querySelector('dialog')?.open === false"))
        }
    }

    private fun awaitReady(scenario: ActivityScenario<MainActivity>) {
        assertTrue("The formal redesign did not become ready.", waitFor(scenario, """
            window.__fujimiApp?.ready === true
              && typeof window.__fujimiNavigate === 'function'
              && !!document.querySelector('fujimi-app')?.shadowRoot
        """.trimIndent()))
    }

    private fun navigate(scenario: ActivityScenario<MainActivity>, view: String) {
        val quoted = JSONObject.quote(view)
        evaluate(scenario, """
            window.__redesignDeviceNavigationError = null;
            Promise.resolve(window.__fujimiNavigate($quoted))
              .catch(error => { window.__redesignDeviceNavigationError = String(error); });
            true
        """.trimIndent())
        assertTrue("Navigation to $view did not complete.", waitFor(scenario,
            "window.__fujimiApp?.view === $quoted && !window.__redesignDeviceNavigationError"))
    }

    private fun evaluate(scenario: ActivityScenario<MainActivity>, script: String): String {
        val done = CountDownLatch(1)
        var result = ""
        scenario.onActivity { activity ->
            activity.webView.evaluateJavascript(script) { value -> result = value; done.countDown() }
        }
        assertTrue("WebView callback timed out.", done.await(10, TimeUnit.SECONDS))
        return result
    }

    private fun waitFor(scenario: ActivityScenario<MainActivity>, condition: String): Boolean {
        val deadline = SystemClock.uptimeMillis() + TimeUnit.SECONDS.toMillis(60)
        while (SystemClock.uptimeMillis() < deadline) {
            if (evaluate(scenario, "Boolean($condition)") == "true") return true
            SystemClock.sleep(150)
        }
        return false
    }
}
