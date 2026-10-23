package jp.fujimi.newsbunko.next

import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.google.zxing.client.android.Intents
import com.journeyapps.barcodescanner.CaptureActivity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PairingScannerDeviceTest {
    @Test fun pairingCameraOpensInPortrait() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val intent = Intent(context, CaptureActivity::class.java)
            .setAction(Intents.Scan.ACTION)
            .putExtra(Intents.Scan.FORMATS, "QR_CODE")
            .putExtra(Intents.Scan.ORIENTATION_LOCKED, false)
            .putExtra(Intents.Scan.BEEP_ENABLED, false)
        ActivityScenario.launch<CaptureActivity>(intent).use { scenario ->
            scenario.onActivity { scanner ->
                assertEquals("扫码界面应保持竖屏", Configuration.ORIENTATION_PORTRAIT,
                    scanner.resources.configuration.orientation)
                val display = scanner.resources.displayMetrics
                assertTrue("相机预览窗口应高于宽", display.heightPixels > display.widthPixels)
            }
        }
    }
}
