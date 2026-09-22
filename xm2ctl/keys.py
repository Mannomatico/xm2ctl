"""Parsing and formatting of button mappings."""

from __future__ import annotations

from .protocol import (
    MAP_CPI_LOOP,
    MAP_DISABLE,
    MAP_KEYBOARD,
    MAP_MEDIA,
    MAP_MOUSE,
    MAP_SCROLL,
    MOUSE_BUTTONS,
)

MODIFIERS = {
    "ctrl": 0x01, "shift": 0x02, "alt": 0x04, "super": 0x08,
    "rctrl": 0x10, "rshift": 0x20, "ralt": 0x40, "rsuper": 0x80,
}

KEYS: dict[str, int] = {chr(c): 0x04 + c - ord("a") for c in range(ord("a"), ord("z") + 1)}
KEYS.update({str(n): 0x1E + n - 1 for n in range(1, 10)})
KEYS.update({f"f{n}": 0x3A + n - 1 for n in range(1, 13)})
KEYS.update({
    "0": 0x27, "enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B,
    "space": 0x2C, "minus": 0x2D, "equal": 0x2E, "capslock": 0x39,
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48, "insert": 0x49,
    "home": 0x4A, "pageup": 0x4B, "delete": 0x4C, "end": 0x4D, "pagedown": 0x4E,
    "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
})

MEDIA = {
    "play-pause": 0xCD, "next": 0xB5, "previous": 0xB6, "mute": 0xE2,
    "volume-up": 0xE9, "volume-down": 0xEA,
}

HELP = (
    "mouse:left|right|middle|back|forward, key:f5 / key:ctrl+c, "
    "media:" + "|".join(MEDIA) + ", scroll:up|down, cpi-loop, disable"
)


def parse_action(text: str) -> bytes:
    """Turn e.g. 'key:ctrl+c' into the 6 mapping bytes [type, value...]."""
    kind, _, arg = text.lower().partition(":")
    if kind == "mouse" and arg in MOUSE_BUTTONS:
        return bytes([MAP_MOUSE, MOUSE_BUTTONS[arg]])
    if kind == "scroll" and arg in ("up", "down"):
        return bytes([MAP_SCROLL, 0x01 if arg == "up" else 0xFF])
    if kind == "media" and arg in MEDIA:
        return bytes([MAP_MEDIA, MEDIA[arg]])
    if kind == "cpi-loop" and not arg:
        return bytes([MAP_CPI_LOOP, 0xF1])
    if kind == "disable" and not arg:
        return bytes([MAP_DISABLE])
    if kind == "key" and arg:
        *mods, key = arg.split("+")
        if key not in KEYS or any(m not in MODIFIERS for m in mods):
            raise ValueError(f"unknown key combination '{arg}'")
        mask = 0
        for mod in mods:
            mask |= MODIFIERS[mod]
        return bytes([MAP_KEYBOARD, mask, KEYS[key]])
    raise ValueError(f"invalid action '{text}'. Expected one of: {HELP}")


def format_action(mapping: bytes) -> str:
    mapping = mapping.ljust(6, b"\0")
    kind, value = mapping[0], mapping[1]
    if kind == MAP_MOUSE:
        names = [name for name, bit in MOUSE_BUTTONS.items() if bit == value]
        return f"mouse:{names[0]}" if names else f"mouse:{value:#04x}"
    if kind == MAP_SCROLL:
        return {0x01: "scroll:up", 0xFF: "scroll:down"}.get(value, f"scroll:{value:#04x}")
    if kind == MAP_MEDIA:
        names = [name for name, code in MEDIA.items() if code == value]
        return f"media:{names[0]}" if names else f"media:{value:#04x}"
    if kind == MAP_CPI_LOOP:
        return "cpi-loop"
    if kind == MAP_DISABLE:
        return "disable"
    if kind == MAP_KEYBOARD:
        mods = [name for name, bit in MODIFIERS.items() if mapping[1] & bit]
        keys = [name for name, code in KEYS.items() if code == mapping[2]]
        key = keys[0] if keys else f"{mapping[2]:#04x}"
        return "key:" + "+".join([*mods, key])
    return "raw:" + mapping.hex(" ")
