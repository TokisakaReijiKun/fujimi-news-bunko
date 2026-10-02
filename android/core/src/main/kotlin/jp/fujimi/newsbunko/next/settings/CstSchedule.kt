package jp.fujimi.newsbunko.next.settings

import java.time.Instant
import java.time.LocalTime
import java.time.ZoneId

/** Strictly schedules a future CST edition; missed editions are never replayed. */
object CstSchedule {
    val zone: ZoneId = ZoneId.of("Asia/Shanghai")
    fun next(time: String, now: Instant): Instant {
        require(Regex("(?:[01]\\d|2[0-3]):[0-5]\\d").matches(time)) { "更新时间须为 HH:mm。" }
        val today = now.atZone(zone).toLocalDate()
        val candidate = today.atTime(LocalTime.parse(time)).atZone(zone).toInstant()
        return if (candidate > now) candidate else today.plusDays(1).atTime(LocalTime.parse(time)).atZone(zone).toInstant()
    }
    fun accept(expected: Instant, now: Instant): Boolean = now >= expected &&
        now.epochSecond - expected.epochSecond <= 7200 &&
        expected.atZone(zone).toLocalDate() == now.atZone(zone).toLocalDate()
    fun reconcile(time: String, now: Instant, pending: Instant?, preservePending: Boolean): Instant {
        val future = next(time, now)
        return if (preservePending && pending != null && (pending > now || accept(pending, now))) pending else future
    }
}
