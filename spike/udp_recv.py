"""
UDP receiver and session recorder for csi_udp firmware.

Usage:
  uv run python spike/udp_recv.py                       # print only, no file, runs until Ctrl-C
  uv run python spike/udp_recv.py empty                 # record to recordings/empty_<date>.csv, runs until Ctrl-C
  uv run python spike/udp_recv.py empty 60              # record exactly 60 seconds then stop

Labels: empty, walk, fall, fan, or any word.
Duration: seconds (integer). Omit to run until Ctrl-C.

CSV columns:
  wall_time_ms  – milliseconds since epoch (laptop clock, UTC)
  board_ip      – IP address the packet arrived from
  board         – board letter (A/B/C/D) once known, else the IP
  raw_line      – the original line from the board, unchanged

Comment lines (starting with #) are included so boot and heartbeat messages are preserved.
"""
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOST = "0.0.0.0"
PORT = 5005

# Known board IPs — updated live from boot/heartbeat lines
BOARD_IPS: dict[str, str] = {
    "192.168.29.87":  "A",
    "192.168.29.37":  "B",
    "192.168.29.137": "C",
    "192.168.29.249": "D",
}


def board_name(ip: str, line: str) -> str:
    """Return board letter for ip, updating the map if a boot/heartbeat line is seen."""
    if line.startswith("# board "):
        parts = line.split()
        if len(parts) >= 3:
            BOARD_IPS[ip] = parts[2]
    elif line.startswith("# heartbeat board="):
        parts = line.split()
        if len(parts) >= 2:
            BOARD_IPS[ip] = parts[1][6:]  # board=X -> X
    return BOARD_IPS.get(ip, ip)


def main():
    label    = sys.argv[1] if len(sys.argv) > 1 else None
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else None  # seconds, optional

    outfile = None
    if label:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = Path("recordings") / f"{label}_{stamp}.csv"
        path.parent.mkdir(exist_ok=True)
        outfile = path.open("w", buffering=1, encoding="utf-8")  # line-buffered
        outfile.write("wall_time_ms,board_ip,board,raw_line\n")
        print(f"# recording to {path}", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    print(f"# listening on UDP {HOST}:{PORT}  —  label={label or '(none, print only)'}  —  {'auto-stop after ' + str(duration) + 's' if duration else 'Ctrl-C to stop'}",
          flush=True)

    start_ms = None   # set on first packet with data

    try:
        while True:
            data, (ip, _) = sock.recvfrom(65535)
            wall_ms = int(time.time() * 1000)
            for line in data.decode(errors="replace").splitlines():
                board = board_name(ip, line)
                # always print to console
                print(f"[{board}] {line}", flush=True)
                # write to CSV if recording
                if outfile:
                    safe = line.replace('"', '""')
                    outfile.write(f'{wall_ms},{ip},{board},"{safe}"\n')
                # auto-stop after duration
                if duration:
                    if start_ms is None and not line.startswith("#"):
                        start_ms = wall_ms
                        print(f"# first data packet — stopping in {duration}s", flush=True)
                    if start_ms and (wall_ms - start_ms) >= duration * 1000:
                        print(f"# {duration}s reached, stopping", flush=True)
                        raise KeyboardInterrupt
    except KeyboardInterrupt:
        print("\n# stopped", flush=True)
    finally:
        sock.close()
        if outfile:
            outfile.close()
            print(f"# saved {path}", flush=True)


if __name__ == "__main__":
    main()
