"""hidraw access for the XM2w 4k using only the Python standard library."""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path

from .protocol import (
    ACK_OK,
    COMMAND_SIZE,
    CONFIG_REQUEST_SIZE,
    OP_BATTERY,
    OP_DEVICE_INFO,
    OP_DONGLE_INFO,
    OP_LOAD_CONFIG,
    OP_SYNC,
    OP_WRITE_ADVANCED,
    OP_WRITE_BASIC,
    OP_WRITE_BUTTONS,
    PID_DONGLE,
    PID_WIRED,
    REPORT_ID_COMMAND,
    REPORT_ID_CONFIG,
    VENDOR_ID,
    WRITE_CHUNK_INDEX,
    WRITE_MARKER,
    WRITE_PAYLOAD_OFFSET,
    Config,
)

HIDRAW_ROOT = Path("/sys/class/hidraw")

# Delays observed in the official tool before it polls for a reply.
REPLY_DELAY_WIRED = 0.5
REPLY_DELAY_DONGLE = 1.0


class DeviceError(Exception):
    pass


def _ioc_rw(nr: int, size: int) -> int:
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


def _find_node() -> tuple[Path, int]:
    """Return (/dev/hidrawN, product_id) of the vendor config interface."""
    for node in sorted(HIDRAW_ROOT.iterdir()):
        uevent = (node / "device" / "uevent").read_text()
        hid_id = next((l for l in uevent.splitlines() if l.startswith("HID_ID=")), None)
        if hid_id is None:
            continue
        _bus, vid, pid = (int(part, 16) for part in hid_id.split("=", 1)[1].split(":"))
        if vid != VENDOR_ID or pid not in (PID_WIRED, PID_DONGLE):
            continue
        descriptor = (node / "device" / "report_descriptor").read_bytes()
        if bytes([0x85, REPORT_ID_COMMAND]) in descriptor:
            return Path("/dev") / node.name, pid
    raise DeviceError("XM2w 4k not found. Is the mouse or dongle plugged in?")


class Device:
    def __init__(self) -> None:
        self.path, self.product_id = _find_node()
        try:
            self._fd = os.open(self.path, os.O_RDWR)
        except PermissionError as exc:
            raise DeviceError(
                f"no permission for {self.path}. Install the udev rule and replug the mouse."
            ) from exc

    def __enter__(self) -> Device:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        os.close(self._fd)

    @property
    def is_wired(self) -> bool:
        return self.product_id == PID_WIRED

    # --- low level -------------------------------------------------------

    def _set_feature(self, data: bytes) -> None:
        buf = bytearray(data)
        fcntl.ioctl(self._fd, _ioc_rw(0x06, len(buf)), buf)

    def _get_feature(self, report_id: int, length: int) -> bytes:
        buf = bytearray(length)
        buf[0] = report_id
        fcntl.ioctl(self._fd, _ioc_rw(0x07, length), buf)
        return bytes(buf)

    def _send(self, data: bytes) -> None:
        if not self.is_wired:
            # The official tool sends this before every command over the dongle.
            self._set_feature(bytes([REPORT_ID_COMMAND, OP_SYNC, 0x01]).ljust(COMMAND_SIZE, b"\0"))
            self._get_feature(REPORT_ID_COMMAND, COMMAND_SIZE)
        self._set_feature(data.ljust(COMMAND_SIZE, b"\0"))

    def _query(self, opcode: int, delay: float = 0.15) -> bytes:
        self._send(bytes([REPORT_ID_COMMAND, opcode]))
        time.sleep(delay if self.is_wired else delay * 2)
        reply = self._get_feature(REPORT_ID_COMMAND, COMMAND_SIZE)
        if reply[1] != ACK_OK:
            raise DeviceError(f"command {opcode:#04x} failed with status {reply[1]:#04x}")
        return reply

    # --- information -----------------------------------------------------

    def mouse_firmware(self) -> str:
        reply = self._query(OP_DEVICE_INFO)
        return f"{reply[22]:x}.{reply[23]:02x}"

    def dongle_firmware(self) -> str | None:
        if self.is_wired:
            return None
        reply = self._query(OP_DONGLE_INFO)
        return f"{reply[16]:x}.{reply[17]:02x}"

    def battery_percent(self) -> int:
        return self._query(OP_BATTERY, delay=0.3)[16]

    # --- config ----------------------------------------------------------

    def read_config(self) -> Config:
        self._send(bytes([REPORT_ID_COMMAND, OP_LOAD_CONFIG]))
        time.sleep(0.12 if self.is_wired else 0.4)
        return Config(self._get_feature(REPORT_ID_CONFIG, CONFIG_REQUEST_SIZE))

    def _write_block(self, opcode: int, payload: bytes, chunk: int = 0) -> None:
        buf = bytearray(COMMAND_SIZE)
        buf[0:4] = bytes([REPORT_ID_COMMAND, opcode, WRITE_MARKER, len(payload)])
        buf[WRITE_CHUNK_INDEX] = chunk
        buf[WRITE_PAYLOAD_OFFSET:WRITE_PAYLOAD_OFFSET + len(payload)] = payload
        self._send(bytes(buf))
        time.sleep(REPLY_DELAY_WIRED if self.is_wired else REPLY_DELAY_DONGLE)
        ack = self._get_feature(REPORT_ID_COMMAND, COMMAND_SIZE)
        if ack[1] != ACK_OK:
            raise DeviceError(f"device rejected block {opcode:#04x}: status {ack[1]:#04x}")

    def write_config(self, old: Config, new: Config) -> None:
        """Send every settings block that changed from old to new, then verify."""
        if new.basic_payload() != old.basic_payload():
            self._write_block(OP_WRITE_BASIC, new.basic_payload())
        if new.advanced_payload() != old.advanced_payload():
            self._write_block(OP_WRITE_ADVANCED, new.advanced_payload())
        for index, (payload_old, payload_new) in enumerate(
            zip(old.button_payloads(), new.button_payloads()), start=1
        ):
            if payload_new != payload_old:
                self._write_block(OP_WRITE_BUTTONS, payload_new, chunk=index)

        mismatches = new.diff(self.read_config())
        if mismatches:
            offsets = ", ".join(str(off) for off, _, _ in mismatches)
            raise DeviceError(f"verification failed, bytes differ at offsets: {offsets}")
