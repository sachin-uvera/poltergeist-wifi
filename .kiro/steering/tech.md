# Tech conventions

## Hardware

Four ESP32-D0WD-V3 DevKit boards, all on 2.4 GHz Wi-Fi channel 6, streaming CSI at 100 packets/s.

| Board | USB chip | MAC | Flash method |
|---|---|---|---|
| A | CH9102 | `20:9b:a9:60:e1:6c` | Arduino IDE Upload button |
| B | CH9102 | `8c:94:df:61:43:b8` | Arduino IDE Upload button |
| C | CP210x | `8c:94:df:90:59:dc` | Piece-by-piece (see work plan appendix) |
| D | CP210x | `00:70:07:a3:db:18` | Piece-by-piece (see work plan appendix) |

## Firmware

- **Arduino core 3.3.11** via `arduino-cli`. Do not switch to ESP-IDF.
- CSI is enabled via `CONFIG_ESP_WIFI_CSI_ENABLED=y` (already compiled into this core).
- Wi-Fi credentials live in a gitignored `secrets.h`. Never hardcode them.
- Serial line format: `CSI,<ms>,<rssi>,<len>,<values…>`
- The board prints its MAC address on boot so the hub can identify it.

## Serial port rules

- Always open serial ports with **DTR=False and RTS=False**. Asserting either line holds these boards in reset.
- Never identify a board by its COM port number. COM ports change when the USB socket changes. Use the MAC address printed on boot.

## Hub (Python)

- Run everything with **`uv`**. No global pip installs.
- Read all 4 serial ports concurrently and tag each packet with the board MAC before any processing.
- All thresholds and configurable values live in one config file so the MCP server can read and update them at runtime.

## Detection approach

- Detection uses **configurable thresholds**, not a trained ML model.
- The motion score starts from the spike metric (variance of CSI amplitudes across subcarriers).
- An empty-room baseline ("exorcise the room") is captured per link before each session.

## Testing

- **Replay mode** runs recorded sessions through the identical code path as live data. Every feature must work in replay mode.
- **Property-based tests** cover the signal math: filters never output NaN, and the motion score rises when disturbance is injected.
- Labelled recordings in `recordings/` are the regression dataset.
