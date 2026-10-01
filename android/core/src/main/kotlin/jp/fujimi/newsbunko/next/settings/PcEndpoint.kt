package jp.fujimi.newsbunko.next.settings

import java.net.URI

object PcEndpoint {
    fun normalize(value: String): String {
        val uri = URI(value.trim())
        require(uri.scheme == "https" && uri.userInfo == null && uri.rawQuery == null && uri.rawFragment == null && uri.path in listOf("", "/")) { "请填写 HTTPS 私网地址，不含路径、账号或查询参数。" }
        require(uri.port == -1 || uri.port in 1..65535) { "端口须为 1–65535。" }
        val host = uri.host ?: throw IllegalArgumentException("请输入私网 IP 地址。")
        val octets = host.split('.').mapNotNull { it.toIntOrNull() }
        require(octets.size == 4 && octets.all { it in 0..255 } && host == octets.joinToString(".")) { "请输入 IPv4 私网地址。" }
        require(octets[0] == 10 || octets[0] == 172 && octets[1] in 16..31 || octets[0] == 192 && octets[1] == 168) { "仅支持局域网或 VPN 私网地址。" }
        return "https://$host${if (uri.port == -1) "" else ":${uri.port}"}"
    }
}
