#!/bin/sh
# Build the HID-BPF fix for the running kernel.
# Needs: clang, bpftool, libbpf-devel, kernel-headers (Fedora package names).
set -eu
cd "$(dirname "$0")"

NAME=0010-EndgameGear__XM2w-4k
bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h
clang -g -O2 -Wall -Wno-missing-declarations -target bpf -D__TARGET_ARCH_x86 -I. -c "$NAME.bpf.c" -o "$NAME.bpf.o"
echo "Built hid-bpf/$NAME.bpf.o"
