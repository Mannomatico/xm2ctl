"""Tests for the deep sleep guard (no hardware needed)."""

import time
import unittest

from xm2ctl.device import ActivityWatch
from xm2ctl.protocol import OFF_DEEP_SLEEP, OFF_POWER_SAVING
from xm2ctl.server import MouseService

from test_protocol import sample_config


class ActivityWatchTest(unittest.TestCase):
    def watch(self, seconds_ago):
        watch = ActivityWatch()
        watch.check = lambda: watch.last_activity  # no hidraw access
        watch.last_activity = None if seconds_ago is None else time.monotonic() - seconds_ago
        return watch

    def test_no_movement_seen_means_asleep(self):
        self.assertFalse(self.watch(None).awake(600))

    def test_recent_movement_means_awake(self):
        self.assertTrue(self.watch(100).awake(600))

    def test_margin_before_sleep(self):
        self.assertFalse(self.watch(100).awake(120))  # 30 s margin: only 90 s are safe
        self.assertTrue(self.watch(20).awake(60))

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


if __name__ == "__main__":
    unittest.main()
