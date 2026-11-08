package jp.fujimi.newsbunko.next.daily

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import jp.fujimi.newsbunko.next.settings.CstSchedule
import jp.fujimi.newsbunko.next.settings.DailyScheduleService
import org.json.JSONObject
import java.time.Instant
import java.util.UUID

class AndroidDailySchedule(private val context: Context) : DailyScheduleService {
    private val preferences = context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE)
    private val manager = context.getSystemService(AlarmManager::class.java)

    @Synchronized override fun configure(mode: String, time: String): JSONObject {
        require(mode in setOf("manual", "automatic")) { "更新模式不正确。" }
        CstSchedule.next(time, Instant.now())
        val previous = preferences.getString("setting:daily-schedule", null)
        val previousGeneration = preferences.getString("daily-schedule-generation", "")
        val value = JSONObject().put("mode", mode).put("time", time)
        check(preferences.edit().putString("setting:daily-schedule", value.toString())
            .putString("daily-schedule-generation", UUID.randomUUID().toString()).commit()) { "定时设置保存失败。" }
        try { reconcile(false) }
        catch (failure: Exception) {
            preferences.edit().putString("setting:daily-schedule", previous).putString("daily-schedule-generation", previousGeneration).commit()
            try { reconcile(false) } catch (_: Exception) { }
            throw failure
        }
        return status()
    }

    @Synchronized fun reconcile(preservePending: Boolean = true) {
        val schedule = saved()
        if (schedule.optString("mode", "manual") != "automatic") {
            manager.cancel(pending(0))
            check(preferences.edit().remove("next-alarm").remove("alarm-exact").commit()) { "无法取消日刊定时。" }
            return
        }
        val pendingEpoch = preferences.getLong("next-alarm", 0)
        val matchingGeneration = preferences.getString("alarm-generation", "") == preferences.getString("daily-schedule-generation", "")
        val next = CstSchedule.reconcile(schedule.getString("time"), Instant.now(), if (matchingGeneration && pendingEpoch > 0) Instant.ofEpochMilli(pendingEpoch) else null, preservePending).toEpochMilli()
        // An already pending window alarm can still fire today; reopening the app must not
        // replace it with tomorrow's edition. Boot and clock changes explicitly discard it.
        if (preservePending && matchingGeneration && next == pendingEpoch && preferences.getBoolean("alarm-exact", false) == exactAllowed()) return
        val intent = pending(next)
        val exact = exactAllowed()
        var appliedExact = exact
        try {
            if (exact) manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next, intent)
            else manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next, intent)
        } catch (_: SecurityException) {
            appliedExact = false
            manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next, intent)
        }
        if (!preferences.edit().putLong("next-alarm", next).putBoolean("alarm-exact", appliedExact)
                .putString("alarm-generation", preferences.getString("daily-schedule-generation", "")).remove("alarm-error").commit()) {
            manager.cancel(intent)
            error("定时记录保存失败，未保留本次安排。")
        }
    }

    override fun status(): JSONObject {
        val next = preferences.getLong("next-alarm", 0)
        return saved().put("timezone", "Asia/Shanghai").put("scheduler_available", true)
            .put("daily_generation_available", true).put("exact_alarm", exactAllowed())
            .put("schedule_precision", if (preferences.getBoolean("alarm-exact", false) && exactAllowed()) "exact" else "window")
            .put("next_run", if (next > 0 && (next > System.currentTimeMillis() || CstSchedule.accept(Instant.ofEpochMilli(next), Instant.now()))) Instant.ofEpochMilli(next).toString() else JSONObject.NULL)
            .put("background_detail", "系统可能延后后台采集；关机错过不补跑，跨日或延迟超过 2 小时的任务跳过。")
    }

    fun onAlarm(intent: Intent) {
        val expected = intent.getLongExtra("expected", 0)
        val generation = intent.getStringExtra("generation")
        if (saved().optString("mode") != "automatic" || generation != preferences.getString("daily-schedule-generation", "") || expected != preferences.getLong("next-alarm", 0)) return
        val instant = Instant.ofEpochMilli(expected)
        if (CstSchedule.accept(instant, Instant.now())) {
            DailyRuntime.get(context).start(instant.atZone(CstSchedule.zone).toLocalDate().toString(), expected, generation)
        }
        reconcile(false) // A one-shot future alarm avoids replaying missed repeating alarms.
    }

    private fun saved() = JSONObject(preferences.getString("setting:daily-schedule", "{\"mode\":\"manual\",\"time\":\"00:00\"}")!!)
    fun exactAllowed() = Build.VERSION.SDK_INT < 31 || manager.canScheduleExactAlarms()
    private fun pending(expected: Long) = PendingIntent.getBroadcast(context, 3801,
        Intent(context, DailyAlarmReceiver::class.java).setAction(ACTION_RUN)
            .putExtra("expected", expected).putExtra("generation", preferences.getString("daily-schedule-generation", "")),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    companion object { const val ACTION_RUN = "jp.fujimi.newsbunko.next.DAILY_ALARM" }
}

class DailyAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pending = goAsync()
        Thread {
            try {
                val scheduler = AndroidDailySchedule(context.applicationContext)
                if (intent.action == AndroidDailySchedule.ACTION_RUN) scheduler.onAlarm(intent) else scheduler.reconcile(false)
            } catch (_: Exception) {
                context.getSharedPreferences("mobile-settings", Context.MODE_PRIVATE).edit().putString("alarm-error", "日刊定时未能安排，请在设置页重新选择生成方式。").commit()
            } finally { pending.finish() }
        }.start()
    }
}
