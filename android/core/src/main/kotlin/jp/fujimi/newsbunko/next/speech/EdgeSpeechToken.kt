package jp.fujimi.newsbunko.next.speech

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Edge v2 request format, adapted from edge-tts drm.py under LGPLv3.
 * https://github.com/rany2/edge-tts/blob/master/src/edge_tts/drm.py
 * Original notices and license: META-INF/edge-tts-LICENSE.txt.
 */
object EdgeSpeechToken {
    const val VERSION = "2-143.0.3650.75"
    private const val MASK = 0xffffffffL
    private val initial = ints("6A09E667 BB67AE85 3C6EF372 A54FF53A 510E527F 9B05688C 1F83D9AB 5BE0CD19")
    private val seed = ints("FD9FBEA2 91243CE7 BE499094 CD2E1E0A 6C006F49 04BD35AB FEB0A7E4 03EFFBD2")
    private val schedule = ints("EB24BF9E 1558691F A0C09EE2 0CFA32BA A622EE8C D1DD9491 C0DD25A0 F9E70AB6 F0C31573 7058CE4E 7188E606 00E5AB33 D258B060 72766564")
    private val constants = ints("428A2F98 71374491 B5C0FBCF E9B5DBA5 3956C25B 59F111F1 923F82A4 AB1C5ED5 D807AA98 12835B01 243185BE 550C7DC3 72BE5D74 80DEB1FE 9BDC06A7 C19BF174 E49B69C1 EFBE4786 0FC19DC6 240CA1CC 2DE92C6F 4A7484AA 5CB0A9DC 76F988DA 983E5152 A831C66D B00327C8 BF597FC7 C6E00BF3 D5A79147 06CA6351 14292967 27B70A85 2E1B2138 4D2C6DFC 53380D13 650A7354 766A0ABB 81C2C92E 92722C85 A2BFE8A1 A81A664B C24B8B70 C76C51A3 D192E819 D6990624 F40E3585 106AA070 19A4C116 1E376C08 2748774C 34B0BCB5 391C0CB3 4ED8AA4A 5B9CCA4F 682E6FF3 748F82EE 78A5636F 84C87814 8CC70208 90BEFFFA A4506CEB BEF9A3F7 C67178F2")
    private val coefficients = longs("E82E91B1 44DE24C6 3BEB65BC C89C5933 8D1EC211 314EF5D5 E92491B1 F0A5B9D5 06064CF3 DA79FA60 BED20560 89F9C9F8 35FA38C6 CB49E3C6")
    private val offsets = longs("B32700D0 88DFF51D 29514038 B328CBDF D405B4D5 26E55F3C 607801C6 82B2C1FB FA51A3DA 207CC464 3C3C74F3 D2D14B61 BB04A2C1 C5626167")
    private fun longs(value: String) = value.split(' ').map { it.toLong(16) }.toLongArray()
    private fun ints(value: String) = longs(value).map { it.toInt() }.toIntArray()
    private fun r(value: Int, n: Int) = Integer.rotateRight(value, n)
    private fun s0(value: Int) = r(value, 7) xor r(value, 18) xor (value ushr 3)
    private fun s1(value: Int) = r(value, 17) xor r(value, 19) xor (value ushr 10)
    private fun swap(value: Long) = Integer.rotateLeft(value.toInt(), 16).toLong() and MASK
    private fun expand(w: IntArray, start: Int) {
        for (i in start until 64) w[i] = s1(w[i - 2]) + w[i - 7] + s0(w[i - 15]) + w[i - 16]
    }
    private fun rounds(input: IntArray, w: IntArray, start: Int = 0): IntArray {
        var a = input[0]; var b = input[1]; var c = input[2]; var d = input[3]
        var e = input[4]; var f = input[5]; var g = input[6]; var h = input[7]
        for (i in start until 64) {
            val k = if (start == 14 && i == 14) 0xC9DC06A7.toInt() else constants[i]
            val t1 = h + (r(e, 6) xor r(e, 11) xor r(e, 25)) + (g xor (e and (f xor g))) + k + w[i]
            val t2 = (r(a, 2) xor r(a, 13) xor r(a, 22)) + ((a and b) or (c and (a or b)))
            h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2
        }
        return intArrayOf(a, b, c, d, e, f, g, h)
    }
    private fun digest(data: ByteArray): ByteArray {
        val w = IntArray(64)
        w[14] = ((data[0].toInt() and 255) shl 16) or ((data[1].toInt() and 255) shl 8) or (data[2].toInt() and 255)
        w[15] = ByteBuffer.wrap(data, 3, 4).int
        for (i in 16 until 30) {
            var value = schedule[i - 16]
            if (i - 2 >= 14) value += if (i == 16) s1(w[i - 2]) xor 0x000B92C0 else s1(w[i - 2])
            if (i - 7 >= 14) value += w[i - 7]
            if (i - 15 >= 14) value += if (i == 29) s0(w[i - 15]) xor 0x059C0B80 else s0(w[i - 15])
            w[i] = value
        }
        w[30] = s1(w[28]) + w[23] + s0(w[15]) + w[14] + 0xC9DC06A7.toInt() - constants[14]
        expand(w, 31)
        var state = rounds(seed, w, 14).mapIndexed { i, x -> initial[i] + x }.toIntArray()
        val length = 57 + data.size
        val zeros = Math.floorMod(55 - length, 64)
        val padded = ByteBuffer.allocate(data.size - 7 + 1 + zeros + 8).put(data, 7, data.size - 7)
            .put(0x80.toByte()).put(ByteArray(zeros)).putLong(length.toLong() * 8).array()
        for (offset in padded.indices step 64) {
            val block = ByteBuffer.wrap(padded, offset, 64)
            val words = IntArray(64)
            for (i in 0 until 16) words[i] = block.int
            expand(words, 16)
            val working = rounds(state, words)
            state = state.mapIndexed { i, x -> x + working[i] }.toIntArray()
        }
        return ByteBuffer.allocate(32).apply { state.forEach { putInt(it) } }.array()
    }
    private fun checksum(data: ByteArray, digest: ByteArray): ByteArray {
        val key = ByteBuffer.wrap(digest).order(ByteOrder.LITTLE_ENDIAN)
        val a = (key.int.toLong() and MASK) or 1L
        val b = (key.int.toLong() and MASK) or 1L
        val factors = longArrayOf(a * 0x82893933L and MASK, b * 0x82893933L and MASK)
        val terms = coefficients.mapIndexed { i, x -> x * factors[i % 2] and MASK }.toMutableList()
        val additions = offsets.toMutableList()
        val input = byteArrayOf(0) + data
        val count = ((input.size + 7) / 8) * 2
        val bytes = ByteBuffer.allocate(count * 4).order(ByteOrder.LITTLE_ENDIAN).put(input).apply { rewind() }
        for (i in 0 until count) {
            val word = bytes.int.toLong() and MASK
            var term = word * (if (i % 2 == 0) a else b)
            var add = swap(word) * (if (i % 2 == 0) 0xEF0569FBL else 0xC31713DBL)
            if (i == 0) { term += 0xF2F90B1AL * factors[0]; add += 0x0B1A0000L }
            terms.add(term and MASK); additions.add(add and MASK)
        }
        var swapAcc = 0L; var swapLast = 0L; var state = 0L; var acc = 0L
        for (i in terms.indices step 2) {
            val x = terms[i]; val y = terms[i + 1]
            var t = swap((additions[i] + x) and MASK)
            var q = t * 0x76F50F34L and MASK
            swapAcc = (swapAcc + swap(q) * 0xC3EFEA97L + q) and MASK
            t = swap((additions[i + 1] + y) and MASK); q = t * 0x1881CE3CL and MASK
            swapLast = (swap(q) * 0x35BD1EC9L + q) and MASK
            swapAcc = (swapAcc + swapLast) and MASK
            state = (state * a + x) and MASK
            for (factor in longArrayOf(0xCF98B111L, 0x87085B9FL, 0x12CEB96DL, 0x257E1D83L)) state = swap(state) * factor and MASK
            acc = (acc + state) and MASK
            t = (state * b + y) and MASK
            t = swap(t) * 0xA27416F5L and MASK
            t = swap(t) * 0xD38396FFL and MASK
            state = swap(swap(t) * 0x7C932B89L and MASK) * 0xBFA49F69L and MASK
            acc = (acc + state) and MASK
        }
        return ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
            .putInt((swapLast xor state).toInt()).putInt((swapAcc xor acc).toInt()).array()
    }
    fun atMillis(milliseconds: Long, clientToken: String): String {
        val seconds = (milliseconds / 1000 + 11644473600L) / 300 * 300
        val data = ("${seconds * 10000000L}" + clientToken).toByteArray(Charsets.US_ASCII)
        val hash = digest(data)
        fun hex(value: ByteArray) = value.joinToString("") { "%02X".format(it.toInt() and 255) }
        return hex(checksum(data, hash)) + "-" + hex(hash)
    }
}
