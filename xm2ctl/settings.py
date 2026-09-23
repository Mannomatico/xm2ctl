"""Mapping between the config model and the JSON settings used by the web UI and profiles."""

from __future__ import annotations

from .keys import format_action, parse_action
from .protocol import (
    BUTTONS,
    CPI_COUNT,
    FILTER_BUTTONS,
    OFF_DEEP_SLEEP,
    OFF_POWER_SAVING,
    Config,
)

REMAPPABLE = BUTTONS[1:]  # left can only be swapped via left-handed mode
TIMERS = {"power_saving": OFF_POWER_SAVING, "deep_sleep": OFF_DEEP_SLEEP}
BOOL_SETTINGS = ("angle_snapping", "ripple_control", "motion_sync", "lift_off_led",
                 "slamclick_filter", "jitter_filter")


def config_to_json(cfg: Config) -> dict:
    cpis = [cfg.get_cpi(level) for level in range(1, CPI_COUNT + 1)]
    return {
        "lod": cfg.lod_mm,
        "polling": cfg.polling_rate,
        **{name: getattr(cfg, name) for name in BOOL_SETTINGS},
        **{
            name: {"enabled": cfg.get_timer(offset) is not None,
                   "minutes": cfg.get_timer_minutes(offset)}
            for name, offset in TIMERS.items()
        },
        "cpi_level_count": cfg.cpi_level_count,
        "xy_split": any(split for _x, _y, split in cpis),
        "cpi": [{"x": x, "y": y} for x, y, _split in cpis],
        "left_handed": cfg.left_handed,
        "buttons": {
            button: {
                "action": format_action(cfg.get_mapping(button)),
                "click": cfg.get_click_setting(button) if button in FILTER_BUTTONS else None,
            }
            for button in BUTTONS
        },
    }


def apply_json(cfg: Config, data: dict, wired: bool) -> None:
    """Apply a (partial) settings object to cfg."""
    if "lod" in data:
        cfg.lod_mm = int(data["lod"])
    if "polling" in data and data["polling"] != cfg.polling_rate:
        if wired:
            raise ValueError("The polling rate can only be changed over the wireless receiver.")
        cfg.polling_rate = int(data["polling"])
    for name in BOOL_SETTINGS:
        if name in data:
            setattr(cfg, name, bool(data[name]))
    for name, offset in TIMERS.items():
        if name in data:
            cfg.set_timer(offset, int(data[name]["minutes"]))
            if not data[name]["enabled"]:
                cfg.set_timer(offset, None)
    if "cpi_level_count" in data:
        cfg.cpi_level_count = int(data["cpi_level_count"])
    if "cpi" in data:
        split = bool(data.get("xy_split", False))
        for level, entry in enumerate(data["cpi"][:CPI_COUNT], start=1):
            cfg.set_cpi(level, int(entry["x"]), int(entry["y"]) if split else None)
    # Handedness first, so the button actions sent along with it already match.
    if "left_handed" in data and bool(data["left_handed"]) != cfg.left_handed:
        cfg.left_handed = bool(data["left_handed"])
    for button, entry in data.get("buttons", {}).items():
        if button in REMAPPABLE and entry.get("action"):
            new_mapping = parse_action(entry["action"])
            if new_mapping.ljust(6, b"\0") != cfg.get_mapping(button):
                cfg.set_mapping(button, new_mapping)
        click = entry.get("click")
        if button in FILTER_BUTTONS and click is not None:
            if click in ("safe", "speed"):
                cfg.set_spdt(button, click)
            else:
                cfg.set_debounce(button, int(click))
