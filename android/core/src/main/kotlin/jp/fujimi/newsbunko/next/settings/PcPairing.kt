package jp.fujimi.newsbunko.next.settings

import org.json.JSONObject

data class PcPairing(val url: String, val code: String) {
    companion object {
        fun parseQr(value: String): PcPairing {
            require(value.length <= 4096) { "二维码内容过长。" }
            val payload = JSONObject(value)
            require(payload.optString("type") == "fujimi-sync" && payload.optInt("version") == 2) { "请扫描 PC 设置中的文庫同步二维码。" }
            return PcPairing(PcEndpoint.normalize(payload.getString("url")), validateCode(payload.getString("code")))
        }

        fun validateCode(value: String): String = value.trim().also {
            require(Regex("[0-9]{6}").matches(it)) { "请输入 PC 显示的 6 位配对码。" }
        }
    }
}
