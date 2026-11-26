"""
firmware/flash_chunked.py – flash boards C and D (CP210x USB chip), whose link drops during long writes.

    uv run python firmware/flash_chunked.py COM6 8c:94:df:90:59:dc firmware/csi_node/build/csi_node.ino.bin

HOLD the BOOT button the whole time (tap EN once after pressing it), until it says "done".

1. Reads the chip MAC and stops unless it matches the board you named (C and D use the same
   chip, and COM numbers move between USB sockets).
2. Writes the app in 64 KB pieces at 0x10000, 0x20000, ..., each in its own esptool run
   with up to 5 retries. Uses --no-stub: esptool's helper program does not run on these boards.
   The bootloader and partition table are left as they are (written earlier with the same
   ESP32 core 3.3.11 and the default partition layout).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

CHUNK = 64 * 1024
APP_OFFSET = 0x10000
TRIES = 5


def esptool(port: str, *args: str) -> subprocess.CompletedProcess:
    cmd = ["uvx", "--from", "esptool", "esptool", "--port", port, "--no-stub", *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    port, want_mac, app = sys.argv[1], sys.argv[2].lower(), Path(sys.argv[3])
    data = app.read_bytes()
    pieces = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]
    print(f"{app.name}: {len(data)} bytes, {len(pieces)} pieces of 64 KB", flush=True)

    r = esptool(port, "read-mac")
    macs = [l.split()[-1].lower() for l in r.stdout.splitlines() if l.strip().startswith("MAC:")]
    if not macs:
        print("Could not reach the board. Hold BOOT, tap EN, keep holding BOOT, and run again.")
        print("\n".join(l for l in (r.stdout + r.stderr).splitlines() if "rror" in l)[-300:])
        return 1
    if macs[0] != want_mac:
        print(f"Wrong board: this is {macs[0]}, expected {want_mac}. Nothing was written.")
        return 1
    print(f"board MAC {macs[0]} matches, writing...", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        for n, piece in enumerate(pieces):
            off = APP_OFFSET + n * CHUNK
            f = Path(tmp) / f"part_{n:02d}.bin"
            f.write_bytes(piece)
            for attempt in range(1, TRIES + 1):
                r = esptool(port, "write-flash", hex(off), str(f))
                if r.returncode == 0 and "Hash of data verified" in r.stdout:
                    print(f"  piece {n + 1:2d}/{len(pieces)} @ {hex(off)} ok"
                          + (f" (try {attempt})" if attempt > 1 else ""), flush=True)
                    break
                if attempt == TRIES:
                    print(f"  piece {n + 1} @ {hex(off)} FAILED after {TRIES} tries. Keep holding BOOT "
                          "and run again; the board will not boot until the write completes.")
                    return 1
    print("done: release BOOT and tap EN to start the new firmware")
    return 0


if __name__ == "__main__":
    sys.exit(main())
