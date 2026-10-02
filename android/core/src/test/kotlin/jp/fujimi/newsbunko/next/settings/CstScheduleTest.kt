package jp.fujimi.newsbunko.next.settings

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.time.Instant

class CstScheduleTest {
    @Test fun `next update uses CST even when device is in another timezone`() {
        assertEquals(Instant.parse("2026-10-01T01:00:00Z"), CstSchedule.next("09:00", Instant.parse("2026-09-30T22:00:00Z")))
    }
    @Test fun `missed daily update is scheduled tomorrow rather than run on boot`() {
        assertEquals(Instant.parse("2026-10-02T01:00:00Z"), CstSchedule.next("09:00", Instant.parse("2026-10-01T02:00:00Z")))
        assertEquals(Instant.parse("2026-10-02T01:00:00Z"), CstSchedule.next("09:00", Instant.parse("2026-10-01T01:00:00Z")))
    }
    @Test fun `late queued work cannot create a different daily edition`() {
        val expected = Instant.parse("2026-10-01T15:00:00Z")
        assertTrue(CstSchedule.accept(expected, expected.plusSeconds(300)))
        assertFalse(CstSchedule.accept(expected, expected.plusSeconds(7201)))
        assertFalse(CstSchedule.accept(expected, Instant.parse("2026-10-01T16:00:01Z")))
        assertFalse(CstSchedule.accept(expected, expected.minusSeconds(1)))
    }
    @Test fun `invalid schedule cannot be interpreted as midnight`() {
        for (value in listOf("24:00", "9:00", "12:60", "", "00:00\n")) {
            assertThrows(IllegalArgumentException::class.java) { CstSchedule.next(value, Instant.now()) }
        }
    }
    @Test fun `returning to app retains due alarm but boot discards missed edition`() {
        val expected = Instant.parse("2026-10-01T00:00:00Z")
        val now = expected.plusSeconds(300)
        assertEquals(expected, CstSchedule.reconcile("08:00", now, expected, true))
        assertEquals(Instant.parse("2026-10-02T00:00:00Z"), CstSchedule.reconcile("08:00", now, expected, false))
    }
}
