# CLAUDE.md

Context for AI assistants working on this repository.

## Working agreement

- Code, comments, commit messages and documentation in **English**.
- Explanations and conversation with the maintainer in **German**.
- The maintainer runs Fedora (GNOME, Wayland) with the mouse attached, so hardware tests
  can be run directly (`python3 -m xm2ctl info`). Ask before any command that writes to
  the mouse, and never run commands with `sudo` yourself; hand them to the maintainer.
- Small, low-risk changes (docs, screenshots, small fixes) may be committed directly to
  `main`. Use a feature branch for larger or risky changes. Never push; the maintainer
  pushes.
- Every supported feature must be verified on real hardware before it is documented as
  supported. Mark unverified behaviour as such in code comments and docs.

## Project

Unofficial Linux configuration tool for the Endgame Gear XM2w 4k (v1, mouse firmware
1.10, receiver firmware 1.01). Pure Python standard library, no dependencies.

- `xm2ctl/protocol.py`: config offsets, `Config` model, write payloads
- `xm2ctl/device.py`: hidraw I/O, command/reply handling, writes
- `xm2ctl/keys.py`: button action parsing and formatting
- `xm2ctl/settings.py`: `Config` <-> JSON settings (web UI and profiles)
- `xm2ctl/profiles.py`: named profiles as JSON in `~/.config/xm2ctl/profiles/`
- `xm2ctl/__main__.py`: CLI (`info`, `dump`, `set`, `restore`, `profile`)
- `xm2ctl/server.py`: local web UI service (127.0.0.1:8341), battery monitor, `/api/battery`
- `xm2ctl/web/`: web UI (vanilla HTML/CSS/JS, strict CSP, no inline scripts)
- `gnome-extension/`: GNOME Shell top bar battery indicator and profile switcher
  (`/api/battery`, `/api/profiles`; write token from `$XDG_RUNTIME_DIR/xm2ctl/token`)
- `hid-bpf/`: HID-BPF report descriptor fix for the keyboard bug (GPL-2.0-only)
- `tests/`: unit tests pinned to bytes captured from the official Windows tool
- `PROTOCOL.md`: the reverse engineered protocol; keep it in sync with code changes

Run tests with `python3 -m unittest discover tests`. Deploy locally with `sh install.sh`
(copies to `~/.local/share/xm2ctl` and restarts the `xm2ctl` user service).

## Protocol essentials (details in PROTOCOL.md)

- USB IDs: `3367:1968` cable, `3367:1970` receiver.
- Commands: 64-byte SET_FEATURE on report `0xA1`, reply via GET_FEATURE `0xA1`,
  byte 1 = status (`0x01` OK, `0x08` pending: keep polling, do not resend writes).
- Read config: `A1 12`, then GET_FEATURE on report **`0xA0`** (1041 bytes). Reading via
  `0xA1` returns receiver data in the header when using the receiver.
- Write blocks: `0x14` basic, `0x15` advanced + power, `0x16` buttons (2 chunks).
- Over the receiver, send `A1 0F 01` + read before each command.

## Dangerous commands, never send

- SET_FEATURE on report `0xA0` with first data byte `0x00`: enters the bootloader.
- `A1 13`: factory reset.

## Known facts that were hard to find

- Polling rate: config and write block both store 8000 / rate (`02`/`04`/`08`).
- In wired mode the official tool always writes 1000 Hz.
- Button entries are `[type, value x5, click]`, order left, right, middle, back,
  forward, CPI, wheel up, wheel down, starting at config offset 71.
- Never send a command for the mouse over the receiver unless it moved recently: in
  power saving or deep sleep it can answer `0x03`, and the receiver then blocks all
  commands, often until it is replugged. Service and CLI check for recent movement first
  (`ActivityWatch`, `ensure_awake`). Keep this in mind for any hardware test script.
- Keyboard codes are plain HID usages (F5 = `0x3E`). Linux dropped them because the
  firmware descriptor declares Usage Minimum 1 for the key array; `hid-bpf/` fixes it.
- Related project: https://github.com/qaustria/xm2w (Tauri app). Some of its findings
  differ from ours (left button offset, key code shift); ours are backed by captures.

## Open items

- The JSON settings treat X/Y split as one switch for all levels; mixed per-level split
  (possible via the CLI, not tested on hardware) is lost in profiles.
- Submit the HID-BPF fix upstream to udev-hid-bpf.
- XM2w 4k v2 support needs captures from a v2 owner.
