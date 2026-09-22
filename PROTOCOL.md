# XM2w 4k USB HID protocol

Reverse engineered from USB captures of the official Endgame Gear XM2w 4k Configuration
Tool v1.04 (mouse firmware 1.10, receiver firmware 1.01) and by diffing config dumps.

## Devices

| Connection | USB ID |
|---|---|
| Cable | `3367:1968` |
| Wireless receiver | `3367:1970` |

Both expose two HID interfaces. The vendor interface (usage pages `0xFF01`/`0xFF02`)
carries these reports:

| Report ID | Type | Size | Use |
|---|---|---|---|
| `0xA1` | feature | 63 bytes + ID | commands and replies |
| `0xA0` | feature | 1040 bytes + ID | full config read |
| `0x02` | input | keyboard | output of buttons mapped to keys |
| `0x06` | input | consumer | output of buttons mapped to media keys |

### Keyboard report descriptor bug (firmware 1.10)

The keyboard collection (report `0x02`, 8 bytes: modifiers, reserved, 5 key slots) is
declared as:

    95 05 75 08 15 00 25 65 05 07 19 01 29 65 81 00
                ^ logical min 0    ^ usage min 1

The firmware fills the key slots with plain HID usages (`04` = A) and `00` for empty slots,
which requires usage minimum `0`. With usage minimum `1`, hosts that follow the descriptor
read every value as usage + 1: `04` becomes B and every empty slot becomes usage `01`
(ErrorRollOver). Linux discards reports containing ErrorRollOver, so no key event is ever
delivered. Observed raw report for a button mapped to A:

    02 00 00 00 00 00 04 00   press
    02 00 00 00 00 00 00 00   release

A report descriptor fixup that replaces `19 01` with `19 00` in this collection (for
example with HID-BPF) would fix it. The consumer collection (report `0x06`, media keys) is
declared correctly and works.

## Commands

Every command is a 64-byte SET_FEATURE on report `0xA1`: `[0xA1, opcode, args..., 0...]`.
The reply is read with GET_FEATURE on report `0xA1`; byte 1 is the status, `0x01` = OK.

Over the receiver, the official tool sends `[0xA1, 0x0F, 0x01]` and reads the reply before
every command, and waits longer (about 1 s instead of 0.5 s) before reading replies.

| Opcode | Name | Reply |
|---|---|---|
| `0x0D` | receiver info | receiver firmware at bytes 16–17 (`01 01` = 1.01) |
| `0x0E` | device info | VID/PID at 16–19, mouse firmware at 22–23 (`01 10` = 1.10) |
| `0x0F` | sync (arg `0x01`) | used around commands over the receiver |
| `0x12` | load config | then GET_FEATURE on report `0xA0` with 1041 bytes |
| `0xB4` | battery | percentage at byte 16 |
| `0x14` | write basic settings | ack |
| `0x15` | write advanced + power settings | ack |
| `0x16` | write button mapping (2 chunks) | ack |

Note: reading the config via report `0xA1` works over the cable but returns receiver data
in the header over the receiver. Always read via report `0xA0`.

## Dangerous commands

Never send these unless you know exactly what you are doing:

| Command | Effect |
|---|---|
| SET_FEATURE report `0xA0`, first data byte `0x00` | enters the firmware bootloader (device re-enumerates as `3367:1967`), per the reflash script in [XM2w Control](https://github.com/qaustria/xm2w) |
| `[0xA1, 0x13]` | factory reset |

`[0xA0, 0x11, config...]` (the "store config" command of the OP1 8k v2 used by egctl) is
accepted but ignored by the XM2w 4k; use the write blocks below instead.

## Config layout

Offsets in the buffer returned by GET_FEATURE on report `0xA0`, where index 0 is the
report ID byte.

| Offset | Size | Setting | Encoding |
|---|---|---|---|
| 19 | 1 | deep sleep | bits 0–6 minutes (1–120), bit 7 set = disabled |
| 20 | 1 | power saving | same as deep sleep |
| 21 | 1 | polling rate | 8000 / rate: `02` = 4000, `04` = 2000, `08` = 1000 Hz |
| 22 | 1 | filters | bit `0x01` slamclick, bit `0x10` motion jitter |
| 23 | 1 | unknown | always `00` so far |
| 24 | 1 | LED on lift-off | `1` = on (tool shows "Disable LED on Lift-Off" inverted) |
| 25 | 1 | lift-off distance | `1` = 1 mm, `2` = 2 mm |
| 26 | 1 | angle snapping | `0`/`1` |
| 27 | 1 | ripple control | `0`/`1` (1) |
| 28 | 1 | motion sync | `0`/`1` (1) |
| 29 | 1 | unknown | always `02` so far |
| 30 | 1 | CPI level count | `1`–`4` |
| 51 | 4 × 5 | CPI levels | `[xy_split, x_lo, x_hi, y_lo, y_hi]`, little endian |
| 71 | 8 × 7 | buttons | see below |

(1) 27 and 28 were only observed changing together; the assignment follows egctl.

In wired mode the official tool always displays and writes 1000 Hz, which silently
resets a higher polling rate set over the receiver.

### Buttons

Order: left, right, middle, back, forward, CPI (underside), wheel up, wheel down.
Each entry is 7 bytes: `[type, value × 5, click]`.

| Type | Meaning | Value |
|---|---|---|
| `0x00` | mouse button | bitmask: `01` left, `02` right, `04` middle, `08` back, `10` forward |
| `0x01` | scroll | `01` up, `FF` down |
| `0x02` | keyboard | modifier bitmask (HID), key usage (e.g. `3E` = F5) |
| `0x09` | cycle CPI levels | `F1` |
| `0x20` | media key | consumer usage low byte (e.g. `CD` = play/pause) |
| `0xFF` | disabled | untested, from egctl |

Left-handed mode has no flag; the tool swaps the left and right mapping.

The click byte applies to left, right, middle, back and forward: values below `0xF0` are
the debounce time in ms, `0xF0` = GX safe mode, `0xF1` = GX speed mode (left/right only).

## Write blocks

    [0xA1, opcode, 0x0F, payload_length, 0x00, 0x00, chunk, 0x00 × 9, payload...]

The payload starts at byte 16. After each block the tool waits and reads the ack.

| Opcode | Length | Payload |
|---|---|---|
| `0x14` | 28 | config[23], LED on lift-off, LOD, angle snapping, ripple control, `0x00` (unknown), CPI level count, config[29], then the 20 CPI bytes from offset 51 |
| `0x15` | 10 | motion sync, polling code, filters, power saving, click byte of left, right, middle, back, forward, deep sleep |
| `0x16` | 28 | chunk 1: button entries 1–4, chunk 2: entries 5–8, exactly as in the config |
