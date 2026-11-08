package jp.fujimi.newsbunko.next.settings

import org.json.JSONObject

/** Native scheduling owns atomic setting persistence and actual alarm status. */
interface DailyScheduleService {
    fun configure(mode: String, time: String): JSONObject
    fun status(): JSONObject
}
