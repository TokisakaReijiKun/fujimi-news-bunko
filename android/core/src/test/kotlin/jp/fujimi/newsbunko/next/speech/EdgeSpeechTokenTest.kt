package jp.fujimi.newsbunko.next.speech

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class EdgeSpeechTokenTest {
    // Public upstream SDK client identifier, not a user credential.
    private val client = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
    @Test fun `v2 request tokens match upstream fixed-time vectors`() {
        assertEquals("52BC7A17B50DFEC9-28C4394775C8751CD2F6859C030C06DB1489ACAB3B3A7651831FC26895177ED6", EdgeSpeechToken.atMillis(0L, client))
        assertEquals("52BC7A17B50DFEC9-28C4394775C8751CD2F6859C030C06DB1489ACAB3B3A7651831FC26895177ED6", EdgeSpeechToken.atMillis(1000L, client))
        assertEquals("52BC7A17B50DFEC9-28C4394775C8751CD2F6859C030C06DB1489ACAB3B3A7651831FC26895177ED6", EdgeSpeechToken.atMillis(299000L, client))
        assertEquals("F7535A20A262E331-28675BF85C7106BBF20035A78FCB0B6890813EAD5C3B983EF3424931B720BABB", EdgeSpeechToken.atMillis(300000L, client))
        assertEquals("4906E15DB09D89F6-67173E3045AD3306007121D0BCCF7548C096E47BE2B4F4539BBE63A2B4D50E50", EdgeSpeechToken.atMillis(1735600000000L, client))
        assertEquals("05FE88C5BC071727-9215798C74AC0E5FD32FC2C86803605E8534CEEA90B6DE6C535B9F70D43F8E7A", EdgeSpeechToken.atMillis(1735600299000L, client))
        assertEquals("99E54519B490BE5C-E162DB0977FBDCB9B86DD8148BF1BCDC3C0303176CE39852A42B415935C20654", EdgeSpeechToken.atMillis(1800000000000L, client))
    }
}
