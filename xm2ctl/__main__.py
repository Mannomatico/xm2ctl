"""Command line interface for xm2ctl.

Examples:
    python3 -m xm2ctl info
    python3 -m xm2ctl dump backup.bin
    python3 -m xm2ctl set --lod 1
    python3 -m xm2ctl set --cpi 1 400 --debounce left 10 --power-saving off
    python3 -m xm2ctl set --map forward key:f5 --map back media:play-pause
    python3 -m xm2ctl set --polling 4000        (dongle only)
    python3 -m xm2ctl restore backup.bin
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .device import Device, DeviceError
from .keys import HELP as ACTION_HELP
from .keys import format_action, parse_action
from .protocol import (
    BUTTONS,
    CPI_COUNT,
    DIVIDER_BY_POLLING,
    FILTER_BUTTONS,
    OFF_DEEP_SLEEP,
    OFF_POWER_SAVING,
    SPDT_BUTTONS,
    Config,
)

REMAPPABLE_BUTTONS = BUTTONS[1:]  # left can only be swapped via --left-handed

BACKUP_DIR = Path.home() / ".local" / "state" / "xm2ctl"


def on_off(value: str) -> bool:
    if value not in ("on", "off"):
        raise argparse.ArgumentTypeError("expected 'on' or 'off'")
    return value == "on"


def timer_value(value: str) -> int | None:
    return None if value == "off" else int(value)


def print_config(cfg: Config) -> None:
    def fmt_timer(offset: int) -> str:
        minutes = cfg.get_timer(offset)
        return "off" if minutes is None else f"{minutes} min"

    polling = cfg.polling_rate
    print(f"  LOD               : {cfg.lod_mm} mm")
    raw_polling = cfg.raw[21]
    polling_text = f"{polling} Hz" if polling else "unknown"
    print(f"  polling rate      : {polling_text} (raw {raw_polling:#04x})")
    print(f"  angle snapping    : {'on' if cfg.angle_snapping else 'off'}")
    print(f"  ripple control    : {'on' if cfg.ripple_control else 'off'}")
    print(f"  motion sync       : {'on' if cfg.motion_sync else 'off'}")
    print(f"  lift-off LED      : {'on' if cfg.lift_off_led else 'off'}")
    print(f"  slamclick filter  : {'on' if cfg.slamclick_filter else 'off'}")
    print(f"  jitter filter     : {'on' if cfg.jitter_filter else 'off'}")
    print(f"  power saving      : {fmt_timer(OFF_POWER_SAVING)}")
    print(f"  deep sleep        : {fmt_timer(OFF_DEEP_SLEEP)}")
    print(f"  CPI levels        : {cfg.cpi_level_count}")
    for level in range(1, CPI_COUNT + 1):
        x, y, split = cfg.get_cpi(level)
        value = f"{x} / {y}" if split else str(x)
        print(f"    level {level}         : {value}")
    print(f"  left-handed       : {'on' if cfg.left_handed else 'off'}")
    print("  buttons (action / click mode):")
    for button in BUTTONS:
        mode = cfg.get_click_mode(button) if button in FILTER_BUTTONS else ""
        print(f"    {button:<11}     : {format_action(cfg.get_mapping(button)):<20} {mode}")


def save_backup(cfg: Config) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"backup-{time.strftime('%Y%m%d-%H%M%S')}.bin"
    path.write_bytes(cfg.raw)
    return path


def confirm_and_write(dev: Device, old: Config, new: Config, assume_yes: bool) -> None:
    changes = new.diff(old)
    if not changes:
        print("Nothing to change.")
        return
    print("Bytes to be written:")
    for offset, before, after in changes:
        print(f"  offset {offset:4d}: {before:#04x} -> {after:#04x}")
    if not assume_yes and input("Write to mouse? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        return
    print(f"Backup saved to {save_backup(old)}")
    dev.write_config(old, new)
    print("Written and verified.")


def cmd_info(dev: Device, _args: argparse.Namespace) -> None:
    connection = "wired" if dev.is_wired else "dongle"
    print(f"{dev.path} ({connection})")
    print(f"  mouse firmware    : {dev.mouse_firmware()}")
    dongle = dev.dongle_firmware()
    if dongle:
        print(f"  dongle firmware   : {dongle}")
    print(f"  battery           : {dev.battery_percent()} %")
    print_config(dev.read_config())


def cmd_dump(dev: Device, args: argparse.Namespace) -> None:
    Path(args.file).write_bytes(dev.read_config().raw)
    print(f"Saved to {args.file}")


def cmd_set(dev: Device, args: argparse.Namespace) -> None:
    old = dev.read_config()
    new = old.copy()

    if args.polling is not None:
        if dev.is_wired:
            raise DeviceError("the polling rate can only be changed over the dongle")
        new.polling_rate = args.polling
    if args.left_handed is not None:
        new.left_handed = args.left_handed
    for button, action in args.map or []:
        if button not in REMAPPABLE_BUTTONS:
            raise ValueError(f"'{button}' cannot be remapped; use one of {REMAPPABLE_BUTTONS}")
        new.set_mapping(button, parse_action(action))
    if args.lod is not None:
        new.lod_mm = args.lod
    for name in ("angle_snapping", "ripple_control", "motion_sync", "lift_off_led",
                 "slamclick_filter", "jitter_filter"):
        value = getattr(args, name)
        if value is not None:
            setattr(new, name, value)
    if args.power_saving is not None:
        new.set_timer(OFF_POWER_SAVING, args.power_saving)
    if args.deep_sleep is not None:
        new.set_timer(OFF_DEEP_SLEEP, args.deep_sleep)
    if args.cpi_levels is not None:
        new.cpi_level_count = args.cpi_levels
    for level, x, *rest in args.cpi or []:
        new.set_cpi(int(level), int(x), int(rest[0]) if rest else None)
    for button, ms in args.debounce or []:
        new.set_debounce(button, int(ms))
    for button, mode in args.spdt or []:
        new.set_spdt(button, mode)

    confirm_and_write(dev, old, new, args.yes)


def cmd_restore(dev: Device, args: argparse.Namespace) -> None:
    old = dev.read_config()
    new = Config(Path(args.file).read_bytes())
    new.raw[0:2] = old.raw[0:2]  # keep the fresh response header
    confirm_and_write(dev, old, new, args.yes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xm2ctl", description="Configure the Endgame Gear XM2w 4k")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show current settings")

    dump = sub.add_parser("dump", help="save the raw config to a file")
    dump.add_argument("file")

    restore = sub.add_parser("restore", help="write a previously saved config")
    restore.add_argument("file")
    restore.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    s = sub.add_parser("set", help="change settings")
    s.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    s.add_argument("--lod", type=int, choices=(1, 2))
    s.add_argument("--polling", type=int, choices=sorted(DIVIDER_BY_POLLING),
                   help="polling rate in Hz (dongle only)")
    s.add_argument("--left-handed", type=on_off, metavar="on|off")
    s.add_argument("--map", nargs=2, action="append", metavar=("BUTTON", "ACTION"),
                   help=f"buttons: {', '.join(REMAPPABLE_BUTTONS)}; actions: {ACTION_HELP}")
    s.add_argument("--angle-snapping", type=on_off, metavar="on|off")
    s.add_argument("--ripple-control", type=on_off, metavar="on|off")
    s.add_argument("--motion-sync", type=on_off, metavar="on|off")
    s.add_argument("--lift-off-led", type=on_off, metavar="on|off")
    s.add_argument("--slamclick-filter", type=on_off, metavar="on|off")
    s.add_argument("--jitter-filter", type=on_off, metavar="on|off")
    s.add_argument("--power-saving", type=timer_value, metavar="MIN|off")
    s.add_argument("--deep-sleep", type=timer_value, metavar="MIN|off")
    s.add_argument("--cpi-levels", type=int, choices=range(1, CPI_COUNT + 1))
    s.add_argument("--cpi", nargs="+", action="append", metavar=("LEVEL X", "Y"),
                   help="set a CPI level, e.g. --cpi 2 800 (add Y for X/Y split)")
    s.add_argument("--debounce", nargs=2, action="append", metavar=("BUTTON", "MS"),
                   help=f"multiclick filter; buttons: {', '.join(FILTER_BUTTONS)}")
    s.add_argument("--spdt", nargs=2, action="append", metavar=("BUTTON", "safe|speed"),
                   help=f"GX mode for {' / '.join(SPDT_BUTTONS)}")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "set":
        for entry in args.cpi or []:
            if len(entry) not in (2, 3):
                sys.exit("--cpi expects LEVEL X [Y]")

    handlers = {"info": cmd_info, "dump": cmd_dump, "set": cmd_set, "restore": cmd_restore}
    try:
        with Device() as dev:
            handlers[args.command](dev, args)
    except (DeviceError, ValueError) as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
