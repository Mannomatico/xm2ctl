"""Tests for the config model. Expected payloads were captured from the official tool."""

import unittest

from xm2ctl.keys import format_action, parse_action
from xm2ctl.protocol import CONFIG_MIN_SIZE, OFF_DEEP_SLEEP, OFF_POWER_SAVING, Config

# Config header and button area as read from a mouse (firmware 1.10), offsets 16-127.
SAMPLE = bytes.fromhex(
    "00 80 00 87 85 04 11 00 00 02 01 01 01 02 03 ff"
    "ff 00 01 01 00 00 ff 01 02 ff 00 00 01 03 00 ff"
    "00 01 04 00 90 01 90 01 00 20 03 20 03 00 a4 06"
    "a4 06 00 80 0c 80 0c 00 01 00 00 00 00 f0 00 02"
    "00 00 00 00 f1 00 04 00 00 00 00 0e 00 08 00 00"
    "00 00 10 00 10 00 00 00 00 0f 09 f1 00 00 00 00"
    "08 01 01 00 00 00 00 08 01 ff 00 00 00 00 08 00"
)


def sample_config() -> Config:
    raw = bytearray(CONFIG_MIN_SIZE)
    raw[0:2] = b"\xa1\x01"
    raw[16:16 + len(SAMPLE)] = SAMPLE
    return Config(raw)


class ConfigTest(unittest.TestCase):
    def test_decodes_settings(self):
        cfg = sample_config()
        self.assertEqual(cfg.lod_mm, 2)
        self.assertEqual(cfg.polling_rate, 2000)
        self.assertEqual(cfg.cpi_level_count, 3)
        self.assertEqual(cfg.get_cpi(1), (400, 400, False))
        self.assertEqual(cfg.get_cpi(3), (1700, 1700, False))
        self.assertIsNone(cfg.get_timer(OFF_POWER_SAVING))
        self.assertEqual(cfg.get_timer_minutes(OFF_DEEP_SLEEP), 7)
        self.assertEqual(cfg.get_click_setting("left"), "safe")
        self.assertEqual(cfg.get_click_setting("right"), "speed")
        self.assertEqual(cfg.get_click_setting("middle"), 14)

    def test_basic_payload_matches_capture(self):
        cfg = sample_config()
        cfg.lod_mm = 1
        self.assertEqual(
            cfg.basic_payload().hex(" "),
            "00 00 01 01 01 00 03 02 "
            "00 90 01 90 01 00 20 03 20 03 00 a4 06 a4 06 00 80 0c 80 0c",
        )

    def test_advanced_payload_matches_capture(self):
        cfg = sample_config()
        cfg.polling_rate = 1000
        self.assertEqual(cfg.advanced_payload().hex(" "), "01 08 11 85 f0 f1 0e 10 0f 87")
        cfg.polling_rate = 4000
        self.assertEqual(cfg.advanced_payload()[1], 0x02)
        cfg.polling_rate = 2000
        self.assertEqual(cfg.advanced_payload()[1], 0x04)

    def test_button_payloads_match_capture(self):
        cfg = sample_config()
        cfg.left_handed = False
        cfg.set_mapping("back", parse_action("media:play-pause"))
        cfg.set_mapping("forward", parse_action("key:f5"))
        first, second = cfg.button_payloads()
        self.assertEqual(first.hex(" ")[-20:], "20 cd 00 00 00 00 10")
        self.assertEqual(second.hex(" ")[:20], "02 00 3e 00 00 00 0f")

    def test_left_handed_swaps_main_buttons(self):
        cfg = sample_config()
        self.assertFalse(cfg.left_handed)
        cfg.left_handed = True
        self.assertTrue(cfg.left_handed)
        self.assertEqual(format_action(cfg.get_mapping("left")), "mouse:right")
        self.assertEqual(format_action(cfg.get_mapping("right")), "mouse:left")

    def test_timer_disable_keeps_minutes(self):
        cfg = sample_config()
        cfg.set_timer(OFF_DEEP_SLEEP, None)
        self.assertIsNone(cfg.get_timer(OFF_DEEP_SLEEP))
        self.assertEqual(cfg.get_timer_minutes(OFF_DEEP_SLEEP), 7)

    def test_rejects_invalid_values(self):
        cfg = sample_config()
        with self.assertRaises(ValueError):
            cfg.set_cpi(1, 430)
        with self.assertRaises(ValueError):
            cfg.set_spdt("middle", "safe")
        with self.assertRaises(ValueError):
            cfg.polling_rate = 8000


class KeysTest(unittest.TestCase):
    def test_round_trip(self):
        for action in ("mouse:back", "key:ctrl+shift+esc", "media:mute", "scroll:down",
                       "cpi-loop", "disable"):
            self.assertEqual(format_action(parse_action(action)), action)

    def test_rejects_unknown_key(self):
        with self.assertRaises(ValueError):
            parse_action("key:hyper+x")


if __name__ == "__main__":
    unittest.main()
