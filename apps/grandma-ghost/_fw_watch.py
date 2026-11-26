"""Watch a board's serial output after flashing: boot lines, then the CSI rate.

    uv run --with pyserial python apps/grandma-ghost/_fw_watch.py COM4 [seconds] [--reset]

Opens the port with DTR and RTS released (asserting them holds these boards in reset or
download mode). With --reset it pulses the EN line once to catch the boot messages.
Prints comment lines as they arrive and a per-second count of CSI lines. Never prints
CSI values, and masks the Wi-Fi network name.
"""
import re
import sys
import time

import serial

port = sys.argv[1]
secs = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 25
reset = "--reset" in sys.argv

s = serial.Serial()
s.port, s.baudrate, s.timeout = port, 921600, 0.5
s.dtr = s.rts = False
s.open()
if reset:
    s.rts = True        # pull EN low: reset
    time.sleep(0.15)
    s.rts = False       # release: the board boots normally (DTR/GPIO0 stays high)
    s.reset_input_buffer()

t0 = time.time()
counts: dict[int, int] = {}
senders: dict[str, int] = {}
total = 0
buf = b""
while time.time() - t0 < secs:
    buf += s.read(4096)
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        text = line.decode(errors="replace").strip()
        if text.startswith("CSI-"):
            sec = int(time.time() - t0)
            counts[sec] = counts.get(sec, 0) + 1
            total += 1
            tx = text[4:5]
            senders[tx] = senders.get(tx, 0) + 1
        elif text.startswith("#"):
            print(f"[{time.time() - t0:5.1f}s] {re.sub(r'connecting to .*', 'connecting to <ssid>', text)[:110]}", flush=True)
        elif text:
            print(f"[{time.time() - t0:5.1f}s] ?? {text[:80]!r}", flush=True)
s.close()

rates = [counts.get(i, 0) for i in range(secs)]
print(f"\nCSI lines in {secs} s: {total}")
print("per second:", rates)
print("by sending board:", dict(sorted(senders.items())))
