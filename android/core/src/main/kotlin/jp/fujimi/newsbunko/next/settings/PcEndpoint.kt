package jp.fujimi.newsbunko.next.settings

import java.net.URI

object PcEndpoint {
    fun normalize(value: String): String {
        val uri = URI(value.trim())
        require(uri.scheme in setOf("http", "https") && uri.userInfo == null && uri.rawQuery == null && uri.rawFragment == null && uri.path in listOf("", "/")) { "请填写 PC 显示的连接地址，不含路径、账号或查询参数。" }
        require(uri.port == -1 || uri.port in 1..65535) { "端口须为 1–65535。" }
        val host = uri.host ?: throw IllegalArgumentException("请输入局域网或 Tailscale IPv4 地址。")
        val octets = host.split('.').mapNotNull { it.toIntOrNull() }
        require(octets.size == 4 && octets.all { it in 0..255 } && host == octets.joinToString(".")) { "请输入完整的 IPv4 地址。" }
        val privateLan = octets[0] == 10 || octets[0] == 172 && octets[1] in 16..31 || octets[0] == 192 && octets[1] == 168
        val tailscale = octets[0] == 100 && octets[1] in 64..127
        require(privateLan || tailscale) { "仅支持局域网或 Tailscale 私网地址。" }
        return "${uri.scheme}://$host${if (uri.port == -1) "" else ":${uri.port}"}"
    }
}
