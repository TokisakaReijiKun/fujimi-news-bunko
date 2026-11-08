package jp.fujimi.newsbunko.next

import androidx.test.ext.junit.runners.AndroidJUnit4
import jp.fujimi.newsbunko.next.settings.PcEndpoint
import jp.fujimi.newsbunko.next.settings.PcSyncClient
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.DataInputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.ServerSocket
import java.nio.file.Files
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class PcSyncClientDeviceTest {
    private data class Request(val line: String, val headers: Map<String, String>, val body: ByteArray)

    private fun exchange(response: ByteArray, client: (PcSyncClient) -> Unit): Request {
        val address = NetworkInterface.getNetworkInterfaces().asSequence().flatMap { it.inetAddresses.asSequence() }
            .filterIsInstance<Inet4Address>().first { runCatching { PcEndpoint.normalize("http://${it.hostAddress}") }.isSuccess }
        ServerSocket(0, 1, address).use { server ->
            val executor = Executors.newSingleThreadExecutor()
            try {
                val request = executor.submit<Request> {
                    server.accept().use { socket ->
                        socket.soTimeout = 5000
                        val input = socket.getInputStream()
                        val header = StringBuilder()
                        while (!header.endsWith("\r\n\r\n")) { val next = input.read(); check(next >= 0); header.append(next.toChar()) }
                        val lines = header.toString().split("\r\n")
                        val fields = lines.drop(1).filter { ':' in it }.associate { it.substringBefore(':').lowercase() to it.substringAfter(':').trim() }
                        val body = ByteArray(fields["content-length"]?.toInt() ?: 0)
                        DataInputStream(input).readFully(body)
                        socket.getOutputStream().apply {
                            write("HTTP/1.1 200 OK\r\nContent-Length: ${response.size}\r\nConnection: close\r\n\r\n".toByteArray())
                            write(response); flush()
                        }
                        Request(lines.first(), fields, body)
                    }
                }
                client(PcSyncClient("http://${address.hostAddress}:${server.localPort}", "test-only-token"))
                return request.get(10, TimeUnit.SECONDS)
            } finally { executor.shutdownNow() }
        }
    }

    @Test fun downloadSendsKnownLengthsAndAcceptsAResponseWithoutHash() {
        val temporary = Files.createTempFile("sync-client-", ".zip")
        try {
            val bytes = "zip-response-fixture".toByteArray()
            val request = exchange(bytes) { it.download("article:fixture", temporary, JSONObject().put("audio/七海.mp3", 123456)) }
            assertEquals("POST /api/sync/v2/pull HTTP/1.1", request.line)
            val body = JSONObject(String(request.body, Charsets.UTF_8))
            assertEquals("article:fixture", body.getString("key"))
            assertEquals(123456, body.getJSONObject("known_files").getInt("audio/七海.mp3"))
            assertArrayEquals(bytes, Files.readAllBytes(temporary))
            assertFalse(request.headers.containsKey("x-content-sha256"))
        } finally { Files.deleteIfExists(temporary) }
    }

    @Test fun uploadStreamsOnceWithoutSendingAHashHeader() {
        val temporary = Files.createTempFile("sync-client-", ".zip")
        try {
            val bytes = "zip-upload-fixture".toByteArray(); Files.write(temporary, bytes)
            val request = exchange("{\"status\":\"created\"}".toByteArray()) {
                assertEquals("created", it.upload(temporary).getString("status"))
            }
            assertEquals("POST /api/sync/v2/bundle HTTP/1.1", request.line)
            assertArrayEquals(bytes, request.body)
            assertFalse(request.headers.containsKey("x-content-sha256"))
        } finally { Files.deleteIfExists(temporary) }
    }
}
