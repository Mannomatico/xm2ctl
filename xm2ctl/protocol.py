"""Protocol definitions for the Endgame Gear XM2w 4k (v1).

Everything here was verified against the official Windows tool (v1.04,
firmware 1.10) by diffing config dumps and capturing USB traffic, unless a
comment says otherwise.

Transport: all commands are 64-byte feature reports on report ID 0xA1:
    [0xA1, opcode, ...]
The reply is fetched with GET_FEATURE on report 0xA1 and starts with
[0xA1, status], status 0x01 meaning OK. The full config is fetched with
GET_FEATURE on report 0xA0 after LOAD_CONFIG; this works over the cable and
the dongle alike. Buffer index 0 of the config is the report ID.

Settings are written in blocks:
    [0xA1, opcode, 0x0F, payload_length, 0x00, 0x00, chunk, 12 zero bytes..., payload]
with the payload starting at byte 16.
"""

from __future__ import annotations

VENDOR_ID = 0x3367
PID_WIRED = 0x1968
PID_DONGLE = 0x1970

REPORT_ID_COMMAND = 0xA1
REPORT_ID_CONFIG = 0xA0

OP_DONGLE_INFO = 0x0D  # dongle firmware at reply[16:18]
OP_DEVICE_INFO = 0x0E  # VID/PID at reply[16:20], mouse firmware at reply[22:24]
OP_SYNC = 0x0F  # sent with argument 0x01 around every command over the dongle
OP_LOAD_CONFIG = 0x12
OP_BATTERY = 0xB4  # battery percentage at reply[16] (other bytes unknown)
OP_WRITE_BASIC = 0x14  # "Basic Settings" tab
OP_WRITE_ADVANCED = 0x15  # "Advanced Settings" + "Power Settings" tabs
OP_WRITE_BUTTONS = 0x16  # "Button Mapping" tab, sent in two chunks

WRITE_MARKER = 0x0F
WRITE_CHUNK_INDEX = 6
WRITE_PAYLOAD_OFFSET = 16
ACK_OK = 0x01
ACK_PENDING = 0x08  # reply not ready yet (seen over the receiver); poll again

COMMAND_SIZE = 64
CONFIG_REQUEST_SIZE = 1041
CONFIG_MIN_SIZE = 1038

OFF_DEEP_SLEEP = 19
OFF_POWER_SAVING = 20
OFF_POLLING_DIVIDER = 21  # encoded, see POLLING_BY_CONFIG
OFF_FILTER_FLAGS = 22
OFF_UNKNOWN_23 = 23  # always 0 so far, first byte of the basic block
OFF_LIFT_OFF_LED = 24
OFF_LOD = 25
OFF_ANGLE_SNAPPING = 26
OFF_RIPPLE_CONTROL = 27  # changed together with 28; assignment follows egctl
OFF_MOTION_SYNC = 28
OFF_UNKNOWN_29 = 29  # always 2 so far, last byte of the basic block header
OFF_CPI_LEVEL_COUNT = 30
OFF_CPIS = 51
OFF_BUTTONS = 71

CPI_COUNT = 4
CPI_STRUCT_SIZE = 5  # [xy_split, x_lo, x_hi, y_lo, y_hi]
CPI_MIN, CPI_MAX, CPI_STEP = 50, 26000, 50

BUTTON_STRUCT_SIZE = 7  # [type, value x5, click_filter]
BUTTONS = ("left", "right", "middle", "back", "forward", "cpi", "wheel_up", "wheel_down")
FILTER_BUTTONS = BUTTONS[:5]
SPDT_BUTTONS = ("left", "right")
BUTTONS_PER_CHUNK = 4

MAP_MOUSE = 0x00  # value: button bitmask
MAP_SCROLL = 0x01  # value: 0x01 up, 0xFF down
MAP_KEYBOARD = 0x02  # value: modifier bitmask, HID key usage
MAP_CPI_LOOP = 0x09  # value: 0xF1
MAP_MEDIA = 0x20  # value: consumer usage (low byte)
MAP_DISABLE = 0xFF  # taken from egctl, unverified on this model

MOUSE_BUTTONS = {"left": 0x01, "right": 0x02, "middle": 0x04, "back": 0x08, "forward": 0x10}

FILTER_SLAMCLICK = 0x01
FILTER_JITTER = 0x10

TIMER_DISABLED = 0x80  # bit 7 set = timer disabled, bits 0-6 = minutes
TIMER_MIN, TIMER_MAX = 1, 120

SPDT_SAFE = 0xF0
SPDT_SPEED = 0xF1
DEBOUNCE_MAX_MS = 25  # conservative limit taken from egctl

# Config and write block both store 8000 / rate. Verified for 1000, 2000 and 4000 Hz.
POLLING_BY_CONFIG = {2: 4000, 4: 2000, 8: 1000}
CONFIG_BY_POLLING = {rate: code for code, rate in POLLING_BY_CONFIG.items()}
DIVIDER_BY_POLLING = {rate: 8000 // rate for rate in CONFIG_BY_POLLING}


class _BoolByte:
    """Descriptor exposing a single config byte as a bool."""

    def __init__(self, offset: int) -> None:
        self.offset = offset

    def __get__(self, obj: Config | None, owner: type | None = None):
        if obj is None:
            return self
        return obj.raw[self.offset] != 0

    def __set__(self, obj: Config, value: bool) -> None:
        obj.raw[self.offset] = 1 if value else 0


class Config:
    """Mutable view on a raw config buffer. Unknown bytes are kept untouched."""

    angle_snapping = _BoolByte(OFF_ANGLE_SNAPPING)
    ripple_control = _BoolByte(OFF_RIPPLE_CONTROL)
    motion_sync = _BoolByte(OFF_MOTION_SYNC)
    lift_off_led = _BoolByte(OFF_LIFT_OFF_LED)  # UI: "Disable LED on Lift-Off" is the inverse

    def __init__(self, raw: bytes) -> None:
        if len(raw) < CONFIG_MIN_SIZE:
            raise ValueError(f"config too short: {len(raw)} bytes")
        self.raw = bytearray(raw[:CONFIG_MIN_SIZE])

    def copy(self) -> Config:
        return Config(self.raw)

    # --- scalar settings -------------------------------------------------

    @property
    def lod_mm(self) -> int:
        return self.raw[OFF_LOD]

    @lod_mm.setter
    def lod_mm(self, value: int) -> None:
        if value not in (1, 2):
            raise ValueError("LOD must be 1 or 2 mm")
        self.raw[OFF_LOD] = value

    @property
    def polling_rate(self) -> int | None:
        return POLLING_BY_CONFIG.get(self.raw[OFF_POLLING_DIVIDER])

    @polling_rate.setter
    def polling_rate(self, hz: int) -> None:
        if hz not in CONFIG_BY_POLLING:
            raise ValueError(f"polling rate must be one of {sorted(CONFIG_BY_POLLING)}")
        self.raw[OFF_POLLING_DIVIDER] = CONFIG_BY_POLLING[hz]

    @property
    def cpi_level_count(self) -> int:
        return self.raw[OFF_CPI_LEVEL_COUNT]

    @cpi_level_count.setter
    def cpi_level_count(self, value: int) -> None:
        if not 1 <= value <= CPI_COUNT:
            raise ValueError(f"CPI level count must be 1-{CPI_COUNT}")
        self.raw[OFF_CPI_LEVEL_COUNT] = value

    def _get_filter(self, flag: int) -> bool:
        return bool(self.raw[OFF_FILTER_FLAGS] & flag)

    def _set_filter(self, flag: int, enabled: bool) -> None:
        if enabled:
            self.raw[OFF_FILTER_FLAGS] |= flag
        else:
            self.raw[OFF_FILTER_FLAGS] &= ~flag & 0xFF

    @property
    def slamclick_filter(self) -> bool:
        return self._get_filter(FILTER_SLAMCLICK)

    @slamclick_filter.setter
    def slamclick_filter(self, enabled: bool) -> None:
        self._set_filter(FILTER_SLAMCLICK, enabled)

    @property
    def jitter_filter(self) -> bool:
        return self._get_filter(FILTER_JITTER)

    @jitter_filter.setter
    def jitter_filter(self, enabled: bool) -> None:
        self._set_filter(FILTER_JITTER, enabled)

    # --- power timers ----------------------------------------------------

    def get_timer(self, offset: int) -> int | None:
        """Return minutes, or None if the timer is disabled."""
        value = self.raw[offset]
        return None if value & TIMER_DISABLED else value & 0x7F

    def get_timer_minutes(self, offset: int) -> int:
        """Return the stored minutes, even if the timer is disabled."""
        return self.raw[offset] & 0x7F

    def set_timer(self, offset: int, minutes: int | None) -> None:
        """Set minutes, or pass None to disable while keeping the stored minutes."""
        if minutes is None:
            self.raw[offset] |= TIMER_DISABLED
            return
        if not TIMER_MIN <= minutes <= TIMER_MAX:
            raise ValueError(f"timer must be {TIMER_MIN}-{TIMER_MAX} minutes")
        self.raw[offset] = minutes

    # --- CPI levels ------------------------------------------------------

    def get_cpi(self, level: int) -> tuple[int, int, bool]:
        """Return (x, y, xy_split) for level 1-4."""
        base = self._cpi_base(level)
        x = int.from_bytes(self.raw[base + 1:base + 3], "little")
        y = int.from_bytes(self.raw[base + 3:base + 5], "little")
        return x, y, self.raw[base] != 0

    def set_cpi(self, level: int, x: int, y: int | None = None) -> None:
        """Set a CPI level. Passing y enables X/Y split, omitting it disables split."""
        base = self._cpi_base(level)
        for value in (x, x if y is None else y):
            if not CPI_MIN <= value <= CPI_MAX or value % CPI_STEP:
                raise ValueError(f"CPI must be {CPI_MIN}-{CPI_MAX} in steps of {CPI_STEP}")
        self.raw[base] = 0 if y is None else 1
        self.raw[base + 1:base + 3] = x.to_bytes(2, "little")
        self.raw[base + 3:base + 5] = (x if y is None else y).to_bytes(2, "little")

    @staticmethod
    def _cpi_base(level: int) -> int:
        if not 1 <= level <= CPI_COUNT:
            raise ValueError(f"CPI level must be 1-{CPI_COUNT}")
        return OFF_CPIS + (level - 1) * CPI_STRUCT_SIZE

    # --- buttons ---------------------------------------------------------

    @staticmethod
    def _button_base(button: str) -> int:
        if button not in BUTTONS:
            raise ValueError(f"unknown button '{button}', expected one of {BUTTONS}")
        return OFF_BUTTONS + BUTTONS.index(button) * BUTTON_STRUCT_SIZE

    def get_mapping(self, button: str) -> bytes:
        """Return the 6 mapping bytes [type, value x5] of a button."""
        base = self._button_base(button)
        return bytes(self.raw[base:base + 6])

    def set_mapping(self, button: str, mapping: bytes) -> None:
        if len(mapping) > 6:
            raise ValueError("mapping must be at most 6 bytes")
        base = self._button_base(button)
        self.raw[base:base + 6] = mapping.ljust(6, b"\0")

    @property
    def left_handed(self) -> bool:
        return (self.get_mapping("left")[:2] == bytes([MAP_MOUSE, MOUSE_BUTTONS["right"]])
                and self.get_mapping("right")[:2] == bytes([MAP_MOUSE, MOUSE_BUTTONS["left"]]))

    @left_handed.setter
    def left_handed(self, enabled: bool) -> None:
        primary, secondary = ("right", "left") if enabled else ("left", "right")
        self.set_mapping("left", bytes([MAP_MOUSE, MOUSE_BUTTONS[primary]]))
        self.set_mapping("right", bytes([MAP_MOUSE, MOUSE_BUTTONS[secondary]]))

    def get_click_setting(self, button: str) -> str | int:
        """Return 'safe', 'speed' or the debounce time in ms."""
        value = self.raw[self._button_base(button) + 6]
        return {SPDT_SAFE: "safe", SPDT_SPEED: "speed"}.get(value, value)

    def get_click_mode(self, button: str) -> str:
        """Return 'safe', 'speed' or the debounce time as e.g. '8 ms'."""
        value = self.raw[self._button_base(button) + 6]
        if value == SPDT_SAFE:
            return "safe"
        if value == SPDT_SPEED:
            return "speed"
        return f"{value} ms"

    def set_debounce(self, button: str, ms: int) -> None:
        if button not in FILTER_BUTTONS:
            raise ValueError(f"debounce is only available for {', '.join(FILTER_BUTTONS)}")
        if not 0 <= ms <= DEBOUNCE_MAX_MS:
            raise ValueError(f"debounce must be 0-{DEBOUNCE_MAX_MS} ms")
        self.raw[self._button_base(button) + 6] = ms

    def set_spdt(self, button: str, mode: str) -> None:
        """Set GX mode 'safe' or 'speed' (left/right only). Use set_debounce for 'off'."""
        if button not in SPDT_BUTTONS:
            raise ValueError("SPDT is only available for the left and right button")
        codes = {"safe": SPDT_SAFE, "speed": SPDT_SPEED}
        if mode not in codes:
            raise ValueError("SPDT mode must be 'safe' or 'speed'")
        self.raw[self._button_base(button) + 6] = codes[mode]

    # --- write payloads --------------------------------------------------

    def basic_payload(self) -> bytes:
        """Payload of OP_WRITE_BASIC, byte-identical to the official tool."""
        header = bytes([
            self.raw[OFF_UNKNOWN_23],
            self.raw[OFF_LIFT_OFF_LED],
            self.raw[OFF_LOD],
            self.raw[OFF_ANGLE_SNAPPING],
            self.raw[OFF_RIPPLE_CONTROL],
            0x00,  # unknown; 0 in all captures and in XM2w Control, split is per CPI level
            self.raw[OFF_CPI_LEVEL_COUNT],
            self.raw[OFF_UNKNOWN_29],
        ])
        return header + bytes(self.raw[OFF_CPIS:OFF_CPIS + CPI_COUNT * CPI_STRUCT_SIZE])

    def advanced_payload(self) -> bytes:
        """Payload of OP_WRITE_ADVANCED, byte-identical to the official tool."""
        click_filters = [self.raw[self._button_base(b) + 6] for b in FILTER_BUTTONS]
        return bytes([
            self.raw[OFF_MOTION_SYNC],
            self._polling_write_code(),
            self.raw[OFF_FILTER_FLAGS],
            self.raw[OFF_POWER_SAVING],
            *click_filters,
            self.raw[OFF_DEEP_SLEEP],
        ])

    def _polling_write_code(self) -> int:
        rate = self.polling_rate
        if rate is None:
            raise ValueError(f"unknown polling value {self.raw[OFF_POLLING_DIVIDER]:#04x} in config")
        return DIVIDER_BY_POLLING[rate]

    def button_payloads(self) -> list[bytes]:
        """Payloads of OP_WRITE_BUTTONS, one per chunk of four button structs."""
        size = BUTTONS_PER_CHUNK * BUTTON_STRUCT_SIZE
        return [
            bytes(self.raw[OFF_BUTTONS + i * size:OFF_BUTTONS + (i + 1) * size])
            for i in range(len(BUTTONS) // BUTTONS_PER_CHUNK)
        ]

    def diff(self, other: Config) -> list[tuple[int, int, int]]:
        """Return (offset, old, new) for every data byte that differs from other."""
        return [
            (i, a, b)
            for i, (a, b) in enumerate(zip(other.raw, self.raw))
            if i >= 2 and a != b
        ]
