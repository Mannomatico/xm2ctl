// SPDX-License-Identifier: GPL-2.0-only
/*
 * Endgame Gear XM2w 4k: fix the keyboard collection of the report descriptor.
 *
 * Firmware 1.10 declares the key array of report 0x02 as
 *
 *   0x15, 0x00,  // Logical Minimum (0)
 *   0x25, 0x65,  // Logical Maximum (101)
 *   0x05, 0x07,  // Usage Page (Keyboard)
 *   0x19, 0x01,  // Usage Minimum (1)       <- should be 0
 *   0x29, 0x65,  // Usage Maximum (101)
 *   0x81, 0x00,  // Input (Data,Arr,Abs)
 *
 * but fills the key slots with plain HID usages and 0x00 for empty slots.
 * With Usage Minimum 1 every key is shifted by one and every empty slot
 * decodes as ErrorRollOver, so the kernel drops all keyboard reports and
 * buttons mapped to keyboard keys do nothing. Setting Usage Minimum to 0
 * fixes both problems.
 *
 * The same descriptor is used over the USB cable and the wireless receiver.
 */

#include "vmlinux.h"
#include "hid_bpf.h"
#include "hid_bpf_helpers.h"
#include <bpf/bpf_tracing.h>

#define VID_ENDGAME_GEAR	0x3367
#define PID_XM2W_4K_WIRED	0x1968
#define PID_XM2W_4K_RECEIVER	0x1970

HID_BPF_CONFIG(
	HID_DEVICE(BUS_USB, HID_GROUP_GENERIC, VID_ENDGAME_GEAR, PID_XM2W_4K_WIRED),
	HID_DEVICE(BUS_USB, HID_GROUP_GENERIC, VID_ENDGAME_GEAR, PID_XM2W_4K_RECEIVER)
);

/* Size of the report descriptor of the keyboard/vendor interface. */
#define RDESC_SIZE	156
/* Offset of the key array items shown above. */
#define KEYS_OFFSET	34
#define KEYS_LEN	12
/* Offset of the Usage Minimum value byte. */
#define USAGE_MIN_OFFSET	(KEYS_OFFSET + 7)

static const __u8 broken_keys[KEYS_LEN] = {
	0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x01, 0x29, 0x65, 0x81, 0x00,
};

static __always_inline bool matches_broken_keys(const __u8 *rdesc)
{
	for (int i = 0; i < KEYS_LEN; i++) {
		if (rdesc[KEYS_OFFSET + i] != broken_keys[i])
			return false;
	}
	return true;
}

SEC(HID_BPF_RDESC_FIXUP)
int BPF_PROG(xm2w_4k_fix_rdesc, struct hid_bpf_ctx *hctx)
{
	__u8 *data = hid_bpf_get_data(hctx, 0 /* offset */, HID_MAX_DESCRIPTOR_SIZE);

	if (!data)
		return 0; /* EPERM check */

	if (hctx->size != RDESC_SIZE || !matches_broken_keys(data))
		return 0;

	data[USAGE_MIN_OFFSET] = 0x00;

	return 0;
}

HID_BPF_OPS(xm2w_4k) = {
	.hid_rdesc_fixup = (void *)xm2w_4k_fix_rdesc,
};

SEC("syscall")
int probe(struct hid_bpf_probe_args *ctx)
{
	/* Only bind to the interface with the broken keyboard collection. */
	ctx->retval = -EINVAL;

	if (ctx->rdesc_size == RDESC_SIZE && matches_broken_keys(ctx->rdesc))
		ctx->retval = 0;

	return 0;
}

char _license[] SEC("license") = "GPL";
