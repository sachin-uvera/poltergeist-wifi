#!/usr/bin/env bash
# Flash an app .bin to boards C/D (CP210x), whose link drops during long writes.
# Writes 64 KB pieces at 0x10000+, each with up to 5 retries. HOLD BOOT the whole time.
# Bootloader/partitions are left as they are (already written with the same core).
# Usage: spike/flash_chunked.sh COM6 spike/csi_mesh/build/csi_mesh.ino.bin
set -euo pipefail
port=$1 bin=$2
tmp=$(mktemp -d)
split -b 65536 -d -a 2 "$bin" "$tmp/part_"
off=$((0x10000))
for f in "$tmp"/part_*; do
  for try in 1 2 3 4 5; do
    printf '%s @ 0x%x, try %d\n' "$(basename "$f")" "$off" "$try"
    uvx --from esptool esptool --port "$port" --no-stub write-flash "$off" "$f" >/dev/null 2>&1 && break
    [ "$try" = 5 ] && { echo "FAILED at 0x$(printf %x "$off")"; exit 1; }
  done
  off=$((off + 65536))
done
rm -rf "$tmp"
echo "done; release BOOT and tap EN"
