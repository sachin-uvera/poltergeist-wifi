# Spec: firmware/csi_node

Production ESP32 firmware for Poltergeist. All four boards run the same sketch. Each board broadcasts ESP-NOW beacons so the other boards get CSI from it, and sends the readings to the hub over Wi-Fi UDP. No USB cables needed once flashed.

Built from `spike/csi_udp/csi_udp.ino`.

---

## Architecture

```
Board A ──ESP-NOW──▶ Board B  (B gets CSI-A)
Board A ──ESP-NOW──▶ Board C  (C gets CSI-A)
Board A ──ESP-NOW──▶ Board D  (D gets CSI-A)
         … and so on for every board pair …

Each board ──UDP──▶ Hub (Python, laptop)
```

Four boards give up to 12 directed links (each board hears 3 others). The hub sees all of them, tagged by transmitter and receiver.

---

## Requirements

### R1 — Boot announcement
On startup, after Wi-Fi connects, the board sends one announcement line to both Serial and UDP:

```
# board <X> mac <xx:xx:xx:xx:xx:xx> ch=<n> ip=<ip>
```

- `X` is the board letter (`A`/`B`/`C`/`D`) looked up from the MAC table.
- MAC is lower-case hex with colon separators.
- This is the first line the hub uses to register which IP belongs to which board.

### R2 — CSI line format
Every CSI reading is one line, sent in a UDP batch (see R6):

```
CSI-<tx>,<ms>,<rssi>,<len>,<v0> <v1> … <vN>
```

| Field | Type | Description |
|---|---|---|
| `tx` | char | Letter of the board whose ESP-NOW beacon caused this reading |
| `ms` | uint32, decimal | `millis()` on the receiving board |
| `rssi` | int8, decimal | RSSI of the received beacon in dBm |
| `len` | uint16, decimal | number of int8 values that follow |
| `v0 … vN` | int8, space-separated | raw CSI buffer (interleaved imag, real per subcarrier, LLTF only, up to 128 values) |

This format matches the spike exactly and is what `core/ingest.py` already parses.

### R3 — Heartbeat when idle
If no CSI reading arrives for 5 000 ms, the board sends one heartbeat line to both Serial and UDP:

```
# heartbeat board=<X> ms=<ms> ip=<ip>
```

The heartbeat repeats every 5 s until CSI resumes. It does not interleave with CSI batch lines.

### R4 — Automatic Wi-Fi reconnect
If `WiFi.status() != WL_CONNECTED` is detected in `loop()`:
1. Stop the ESP-NOW beacons.
2. Disable CSI.
3. Print/send `# wifi lost, reconnecting`.
4. Call `WiFi.begin()` and block until reconnected.
5. Re-register the hub IP, restart CSI and ESP-NOW.
6. Print/send `# wifi reconnected`.

The board never requires a manual reset to recover.

### R5 — Secrets in `secrets.h`
Four values defined in `firmware/csi_node/secrets.h` (gitignored):

```cpp
#define WIFI_SSID "your-wifi-name"   // 2.4 GHz, case-sensitive
#define WIFI_PASS "your-wifi-password"
#define HUB_IP    "192.168.x.x"      // laptop IP on the same network
#define HUB_PORT  5005
```

The sketch uses `#if __has_include("secrets.h") … #else #error … #endif` so a missing file fails at compile time with a clear message.

A `secrets.h.example` with the four placeholders is committed to the repo.

### R6 — UDP batched send
CSI lines are batched into one UDP packet per flush. The batch is flushed when:
- the next line would push the batch over 1 400 bytes (fits one Wi-Fi frame), **or**
- `loop()` has drained the queue.

Each UDP packet is also written to Serial so the connection can be monitored with a terminal.

Queue depth: 64 readings. The CSI callback drops rather than blocks if the queue is full.

### R7 — ESP-NOW beacon rate
Each board broadcasts one 1-byte ESP-NOW frame every `SEND_MS = 30` ms (≈33 Hz per board). With 3 other boards transmitting, each board receives ≈100 CSI readings per second.

PHY mode must be **HT20 MCS0** (`WIFI_PHY_RATE_MCS0_LGI`). The default 802.11b rate carries no OFDM training field and produces no CSI.

### R8 — MAC table
Board identity is determined by looking up the station MAC against a hardcoded table:

| Letter | MAC |
|---|---|
| A | `20:9b:a9:60:e1:6c` |
| B | `8c:94:df:61:43:b8` |
| C | `8c:94:df:90:59:dc` |
| D | `00:70:07:a3:db:18` |

Unknown senders and self-reflections are silently dropped in the CSI callback.

### R9 — CSI configuration
LLTF only, identical to the spike:
- `lltf_en = true`, `htltf_en = false`, `stbc_htltf2_en = false`
- `ltf_merge_en = true`, `channel_filter_en = false`, `manu_scale = false`

### R10 — Power save disabled
`WiFi.setSleep(false)` before `WiFi.begin()`. Power save makes CSI bursty.

---

## File layout

```
firmware/csi_node/
├── csi_node.ino        # main sketch (all requirements above)
├── secrets.h           # gitignored; created by the developer
└── secrets.h.example   # committed; four placeholder defines
```

---

## Build and flash

```bash
# Compile
arduino-cli compile --fqbn esp32:esp32:esp32 --output-dir firmware/csi_node/build firmware/csi_node

# Flash boards A and B (CH9102)
arduino-cli upload --fqbn esp32:esp32:esp32 --port <COMx> --input-dir firmware/csi_node/build

# Flash boards C and D (CP210x) — piece-by-piece method, see docs/KIRO_WORKPLAN.md appendix
```

---

## Acceptance criteria

- [ ] All 4 boards flash without errors.
- [ ] Each board prints/sends `# board <X> mac …` as its first line after reset.
- [ ] Board letters match the MAC table in `tech.md`.
- [ ] Hub receives ≈100 `CSI-<tx>` lines per second from each board.
- [ ] `# heartbeat` appears within 6 s when no other board is transmitting.
- [ ] Dropping Wi-Fi triggers a reconnect and CSI resumes without a manual reset.
- [ ] `core/ingest.py` parses the UDP lines with no changes (same format as the spike recordings).
