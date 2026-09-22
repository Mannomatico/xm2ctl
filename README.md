# xm2ctl

Configure the **Endgame Gear XM2w 4k** gaming mouse on Linux, over the USB cable or the
wireless receiver. Comes with a local web UI, a command line tool and a battery monitor
with desktop notifications. Pure Python standard library, no dependencies.

![Web UI](docs/screenshot.png)

> **AI notice:** This project was developed with the assistance of AI (Anthropic's
> Claude). The USB protocol was reverse engineered from captures of the official
> Windows tool, and every feature listed as supported was tested on real hardware
> before release.

> **Disclaimer:** This is an unofficial community project. It is not affiliated with,
> endorsed by or supported by Endgame Gear. "Endgame Gear" and "XM2w" are trademarks of
> their respective owner. Use at your own risk; the official Windows tool's factory reset
> restores the default settings if anything goes wrong.

## Supported devices

| Device | Firmware | Status |
|---|---|---|
| XM2w 4k (v1), USB ID `3367:1968` wired / `3367:1970` receiver | mouse 1.10, receiver 1.01 | tested |

Other Endgame Gear mice use a similar protocol but different product IDs and are not
supported yet. Reports and captures from other models are welcome.

## Features

- Sensor: CPI levels (50–26000 in steps of 50), active level count, lift-off distance,
  polling rate 1000/2000/4000 Hz (receiver only, like the official tool)
- Tracking: angle snapping, ripple control, motion sync, slamclick and jitter filters,
  LED on lift-off
- Clicks: debounce time per button, GX safe/speed mode for the main buttons
- Buttons: remap to mouse buttons, keyboard keys and combinations, media keys, scroll,
  CPI cycling; left-handed mode
- Power: power saving and deep sleep timers
- Battery level, mouse and receiver firmware versions
- Every write is backed up first and verified by reading the config back

Not supported: firmware updates and receiver pairing (use the official tool), X/Y split
CPI values are implemented but not yet verified on hardware.

## Install

    git clone https://github.com/<user>/xm2ctl.git
    cd xm2ctl
    sh install.sh

The script copies the package to `~/.local/share/xm2ctl`, installs a udev rule that gives
the logged-in user access to the mouse (asks for sudo once), starts the `xm2ctl` systemd
user service and adds an "XM2w 4k" launcher to the app grid.

Requirements: Linux with systemd, Python 3.9 or newer, `gdbus` for notifications
(part of GLib, present on GNOME and most desktops).

## Web UI

Open http://127.0.0.1:8341 or start "XM2w 4k" from the app grid. The service checks the
battery every 5 minutes and shows a desktop notification once it drops to 20 % or less.

Options go into `ExecStart` in `~/.config/systemd/user/xm2ctl.service`:

    --port 8341  --low-battery 20  --interval 300

    systemctl --user status xm2ctl
    journalctl --user -u xm2ctl

The server listens on 127.0.0.1 only, rejects requests with a foreign `Host` or `Origin`
header and requires a random per-start token for every write, so other websites open in
your browser cannot change the mouse settings.

## Command line

    cd ~/.local/share/xm2ctl
    python3 -m xm2ctl info
    python3 -m xm2ctl set --lod 1 --debounce left 10 --spdt right safe
    python3 -m xm2ctl set --map forward key:f5 --map back media:play-pause
    python3 -m xm2ctl set --polling 4000        # wireless receiver only
    python3 -m xm2ctl dump config.bin
    python3 -m xm2ctl restore ~/.local/state/xm2ctl/backup-YYYYMMDD-HHMMSS.bin

Run `python3 -m xm2ctl set --help` for all options.

## Protocol

See [PROTOCOL.md](PROTOCOL.md) for the reverse engineered USB HID protocol.

## Development

    python3 -m unittest discover tests

## Credits

- [egctl](https://github.com/Creationsss/egctl) by Creationsss, a configuration tool for
  the Endgame Gear OP1 8k v2. Its source was the starting point for understanding the
  config layout. No code was copied.

## License

MIT, see [LICENSE](LICENSE).
