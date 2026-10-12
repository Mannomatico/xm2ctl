"""Tests for the deep sleep guard (no hardware needed)."""

import time
import unittest

from xm2ctl.device import ActivityWatch
from xm2ctl.protocol import OFF_DEEP_SLEEP, OFF_POWER_SAVING
from xm2ctl.server import MouseService, smooth_battery

from test_protocol import sample_config


class ActivityWatchTest(unittest.TestCase):
    def watch(self, seconds_ago):
        watch = ActivityWatch()
        watch.check = lambda: watch.last_activity  # no hidraw access
        watch.last_activity = None if seconds_ago is None else time.monotonic() - seconds_ago
        watch.active_since = None if seconds_ago is None else watch.last_activity - 60
        return watch

    def test_no_movement_seen_means_asleep(self):
        self.assertFalse(self.watch(None).awake(600))

    def test_recent_movement_means_awake(self):
        self.assertTrue(self.watch(100).awake(600))

    def test_margin_before_sleep(self):
        self.assertFalse(self.watch(100).awake(120))  # 30 s margin: only 90 s are safe
        self.assertTrue(self.watch(20).awake(60))

    def test_waits_after_waking_up(self):
        watch = self.watch(1)
        watch.active_since = time.monotonic() - 2
        self.assertFalse(watch.awake(600))
        watch.active_since = time.monotonic() - 6
        self.assertTrue(watch.awake(600))

    def test_disabled_timers_mean_always_awake(self):
        self.assertTrue(self.watch(None).awake(None))


class ServiceDeepSleepTest(unittest.TestCase):
    def test_idle_limit_is_the_shorter_timer(self):
        service = MouseService(low_battery=20, interval=120)
        self.assertEqual(service.idle_limit, 60.0)  # unknown: assume the shortest timer
        cfg = sample_config()
        cfg.set_timer(OFF_DEEP_SLEEP, 10)
        cfg.set_timer(OFF_POWER_SAVING, 2)
        service._remember(cfg)
        self.assertEqual(service.idle_limit, 120.0)
        cfg.set_timer(OFF_POWER_SAVING, None)
        service._remember(cfg)
        self.assertEqual(service.idle_limit, 600.0)
        cfg.set_timer(OFF_DEEP_SLEEP, None)
        service._remember(cfg)
        self.assertIsNone(service.idle_limit)


class SmoothBatteryTest(unittest.TestCase):
    def test_first_value_and_drops_are_shown_at_once(self):
        self.assertEqual(smooth_battery(None, None, 50, charging=False), (50, None))
        self.assertEqual(smooth_battery(50, None, 45, charging=False), (45, None))

    def test_rise_needs_two_reports(self):
        shown, pending = smooth_battery(45, None, 50, charging=False)
        self.assertEqual((shown, pending), (45, 50))
        self.assertEqual(smooth_battery(shown, pending, 50, charging=False), (50, None))

    def test_flapping_stays_on_the_lower_value(self):
        shown, pending = 45, None
        for value in (50, 45, 50, 45):
            shown, pending = smooth_battery(shown, pending, value, charging=False)
            self.assertEqual(shown, 45)

    def test_charging_rises_at_once(self):
        self.assertEqual(smooth_battery(5, None, 30, charging=True), (30, None))


if __name__ == "__main__":
    unittest.main()
