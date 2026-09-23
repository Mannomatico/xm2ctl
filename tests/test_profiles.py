"""Tests for the JSON settings mapping and profile storage."""

import json
import tempfile
import unittest
from pathlib import Path

from xm2ctl import profiles
from xm2ctl.protocol import OFF_DEEP_SLEEP
from xm2ctl.settings import apply_json, config_to_json

from test_protocol import sample_config


class SettingsJsonTest(unittest.TestCase):
    def test_round_trip_is_lossless(self):
        source = sample_config()
        source.set_mapping("forward", bytes([0x02, 0x01, 0x3E]))  # ctrl+f5
        source.set_cpi(2, 850)  # X/Y split is one switch for all levels in JSON
        target = sample_config()
        target.lod_mm = 1
        target.cpi_level_count = 4
        target.left_handed = True
        target.set_timer(OFF_DEEP_SLEEP, 30)
        apply_json(target, config_to_json(source), wired=False)
        self.assertEqual(target.diff(source), [])

    def test_polling_is_refused_over_the_cable(self):
        cfg = sample_config()
        with self.assertRaises(ValueError):
            apply_json(cfg, {"polling": 4000}, wired=True)


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "profiles"

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_load_list_delete(self):
        settings = config_to_json(sample_config())
        profiles.save("Gaming", settings, self.dir)
        profiles.save("office 2", settings, self.dir)
        self.assertEqual(profiles.list_profiles(self.dir), ["Gaming", "office 2"])
        self.assertEqual(profiles.load("Gaming", self.dir), settings)
        profiles.delete("Gaming", self.dir)
        self.assertEqual(profiles.list_profiles(self.dir), ["office 2"])
        with self.assertRaises(ValueError):
            profiles.load("Gaming", self.dir)

    def test_rejects_unsafe_names(self):
        for name in ("", " ", "../evil", "a/b", ".hidden", "x" * 41, None):
            with self.assertRaises(ValueError):
                profiles.save(name, {}, self.dir)

    def test_load_all_skips_broken_files(self):
        profiles.save("ok", {"lod": 1}, self.dir)
        (self.dir / "broken.json").write_text("{")
        (self.dir / "old.json").write_text(json.dumps({"format": 99, "settings": {}}))
        self.assertEqual(profiles.load_all(self.dir), {"ok": {"lod": 1}})

    def test_apply_skips_polling_over_the_cable(self):
        cfg = sample_config()
        settings = config_to_json(cfg)
        settings["polling"] = 4000
        settings["lod"] = 1
        notes = profiles.apply(cfg, settings, wired=True)
        self.assertEqual(len(notes), 1)
        self.assertEqual(cfg.polling_rate, 2000)
        self.assertEqual(cfg.lod_mm, 1)
        self.assertEqual(profiles.apply(cfg, settings, wired=False), [])
        self.assertEqual(cfg.polling_rate, 4000)

    def test_matches_ignores_polling_over_the_cable(self):
        current = config_to_json(sample_config())
        profile = dict(current, polling=4000)
        self.assertFalse(profiles.matches(profile, current, wired=False))
        self.assertTrue(profiles.matches(profile, current, wired=True))
        self.assertFalse(profiles.matches(dict(profile, lod=1), current, wired=True))


if __name__ == "__main__":
    unittest.main()
