package jp.fujimi.newsbunko.next.settings

import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class PcEndpointTest {
    @Test fun `tailscale IPv4 range accepts both boundaries and preserves HTTP HTTPS and port`() {
        for (host in listOf("100.64.0.0", "100.64.0.1", "100.100.100.100", "100.127.255.255")) {
            for (scheme in listOf("http", "https")) {
                val address = "$scheme://$host:8429"
                assertEquals(address, PcEndpoint.normalize(" $address/ "))
            }
        }
        assertEquals("http://100.64.0.1:1", PcEndpoint.normalize("http://100.64.0.1:1"))
        assertEquals("https://100.127.255.255:65535", PcEndpoint.normalize("https://100.127.255.255:65535/"))
    }

    @Test fun `public neighbors domains IPv6 and malformed endpoints stay rejected`() {
        val blocked = listOf(
            "http://100.63.255.255:8429", "http://100.128.0.0:8429", "http://100.0.0.1", "http://100.255.255.255",
            "http://8.8.8.8:8429", "http://127.0.0.1:8429", "https://pc.example.com", "https://pc.tail123.ts.net",
            "http://[fd7a:115c:a1e0::1]:8429", "http://[::1]:8429", "http://user:password@100.64.0.1:8429",
            "http://100.64.0.1:8429/api", "http://100.64.0.1:8429?x=1", "http://100.64.0.1:8429#fragment",
            "http://100.64.0.1:0", "http://100.64.0.1:65536", "http://100.64.0.256", "http://100.064.0.1",
            "http://100.64.1", "http://100.64.0.1.", "ftp://100.64.0.1:8429",
        )
        for (address in blocked) assertThrows(IllegalArgumentException::class.java, { PcEndpoint.normalize(address) }, address)
    }

    @Test fun `RFC1918 remains supported while adjacent public ranges stay rejected`() {
        for (host in listOf("10.0.0.1", "10.255.255.254", "172.16.0.1", "172.31.255.254", "192.168.0.1", "192.168.255.254")) {
            assertEquals("http://$host:8429", PcEndpoint.normalize("http://$host:8429/"))
        }
        for (host in listOf("172.15.255.255", "172.32.0.0", "192.167.255.255", "192.169.0.0")) {
            assertThrows(IllegalArgumentException::class.java) { PcEndpoint.normalize("http://$host:8429") }
        }
    }

    @Test fun `QR and manual pairing use the same tailscale address policy and keep zero-prefixed code`() {
        val address = "http://100.64.12.34:8429/"
        val qr = JSONObject().put("type", "fujimi-sync").put("version", 2).put("url", address).put("code", "001234")
        val parsed = PcPairing.parseQr(qr.toString())
        assertEquals(PcEndpoint.normalize(address), parsed.url)
        assertEquals("001234", parsed.code)
        for (bad in listOf("http://100.128.0.1:8429", "https://pc.tail123.ts.net", "http://100.64.0.1:8429/api")) {
            qr.put("url", bad)
            assertThrows(IllegalArgumentException::class.java) { PcPairing.parseQr(qr.toString()) }
        }
    }
}
