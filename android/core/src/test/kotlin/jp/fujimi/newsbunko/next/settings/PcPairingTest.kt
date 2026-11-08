package jp.fujimi.newsbunko.next.settings

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class PcPairingTest {
    @Test fun `scanner accepts a versioned private address and preserves leading zeroes`() {
        val result = PcPairing.parseQr("""{"type":"fujimi-sync","version":2,"url":"http://192.168.1.20:8429/","code":"012345"}""")
        assertEquals("http://192.168.1.20:8429", result.url)
        assertEquals("012345", result.code)
    }

    @Test fun `scanner rejects unrelated or malformed pairing information`() {
        for (value in listOf("https://example.com", "{}",
            """{"type":"fujimi-sync","version":1,"url":"http://192.168.1.20:8429","code":"123456"}""",
            """{"type":"fujimi-sync","version":2,"url":"http://8.8.8.8:8429","code":"123456"}""",
            """{"type":"fujimi-sync","version":2,"url":"http://192.168.1.20:8429","code":"12345x"}""")) {
            assertThrows(Exception::class.java) { PcPairing.parseQr(value) }
        }
    }
}
