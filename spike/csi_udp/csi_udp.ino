// Production-equivalent spike: board-to-board CSI over ESP-NOW, data to hub over Wi-Fi UDP.
//
// All 4 boards run the same sketch. Each board:
//   1. Joins SamSon on ch 6 (data pipe only).
//   2. Broadcasts tiny ESP-NOW frames to all other boards for CSI sensing.
//   3. Collects CSI from every other board's frame.
//   4. Batches readings (2 per packet, under 1400 bytes) and sends them to the hub by UDP.
//
// UDP packet format (newline-delimited lines, one per CSI reading):
//   CSI-<tx>,<ms>,<rssi>,<len>,<v0> <v1> ...
//   tx  = letter of the board whose frame caused this measurement (A/B/C/D)
//   ms  = millis() on the receiving board
//   len = number of int8 values that follow
//   values = interleaved imag,real per subcarrier, LLTF only (up to 128 values)
//
// Boot line on Serial (also sent as first UDP packet on connect):
//   # board <X> mac <xx:xx:xx:xx:xx:xx> ch=6 ip=<ip>
//
// Heartbeat line every 5 s if no CSI arrives (sent to Serial and UDP):
//   # heartbeat board=<X> ms=<ms> ip=<ip>

#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_wifi.h"
#include "esp_mac.h"
#include "esp_now.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy secrets.h.example to secrets.h and fill in WIFI_SSID, WIFI_PASS, HUB_IP, HUB_PORT"
#endif

// ── constants ────────────────────────────────────────────────────────────────
constexpr uint8_t  CHANNEL     = 6;
constexpr uint32_t SEND_MS     = 30;    // ESP-NOW beacon interval (~33 Hz per board)
constexpr uint32_t HEARTBEAT_MS = 5000;
constexpr int      CSI_MAX     = 128;   // LLTF: 64 subcarriers × (imag, real)
constexpr int      MAX_UDP     = 1400;  // fits one Wi-Fi frame (MTU 1500 minus headers)
constexpr int      MAX_LINE    = 700;   // worst-case text line: header + 128 × " -128"

// ── known boards ─────────────────────────────────────────────────────────────
static const uint8_t BOARDS[][6] = {
  {0x20, 0x9b, 0xa9, 0x60, 0xe1, 0x6c},  // A  CH9102
  {0x8c, 0x94, 0xdf, 0x61, 0x43, 0xb8},  // B  CH9102
  {0x8c, 0x94, 0xdf, 0x90, 0x59, 0xdc},  // C  CP210x
  {0x00, 0x70, 0x07, 0xa3, 0xdb, 0x18},  // D  CP210x
};
static const uint8_t BCAST[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

// ── types ─────────────────────────────────────────────────────────────────────
struct CsiReading {
  uint32_t ms;
  char     tx;
  int8_t   rssi;
  uint16_t len;
  int8_t   buf[CSI_MAX];
};

// ── globals ───────────────────────────────────────────────────────────────────
static QueueHandle_t  q;
static WiFiUDP        udp;
static IPAddress      hubIp;
static char           myName    = '?';
static uint32_t       lastCsiMs = 0;

// ── helpers ───────────────────────────────────────────────────────────────────
static char boardName(const uint8_t *mac) {
  for (int i = 0; i < 4; i++)
    if (memcmp(mac, BOARDS[i], 6) == 0) return 'A' + i;
  return 0;
}

// Send a null-terminated string to both Serial and UDP.
static void broadcast(const char *s) {
  Serial.print(s);
  udp.beginPacket(hubIp, HUB_PORT);
  udp.write((const uint8_t *)s, strlen(s));
  udp.endPacket();
}

// ── CSI callback (Wi-Fi task) ─────────────────────────────────────────────────
static void onCsi(void *, wifi_csi_info_t *info) {
  if (!info || !info->buf) return;
  char tx = boardName(info->mac);
  if (!tx) return;                        // ignore unknown senders
  if (tx == myName) return;              // ignore our own reflections

  CsiReading r;
  r.ms   = millis();
  r.tx   = tx;
  r.rssi = info->rx_ctrl.rssi;
  r.len  = info->len > CSI_MAX ? CSI_MAX : info->len;
  memcpy(r.buf, info->buf, r.len);
  xQueueSend(q, &r, 0);                  // drop rather than block Wi-Fi task
}

// ── setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(921600);
  q = xQueueCreate(64, sizeof(CsiReading));

  // ── Wi-Fi: join SamSon on ch 6 ──────────────────────────────────────────
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("# connecting to " WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();

  // Keep the radio on the channel the router assigned (should be ch 6).
  // If the router drifts, all boards drift together, so sensing still works.

  // ── identify this board ──────────────────────────────────────────────────
  uint8_t me[6];
  esp_read_mac(me, ESP_MAC_WIFI_STA);
  myName = boardName(me);

  hubIp.fromString(HUB_IP);
  udp.begin(HUB_PORT);                   // bind local port (reuse same number)

  char hdr[128];
  snprintf(hdr, sizeof(hdr),
           "# board %c mac %02x:%02x:%02x:%02x:%02x:%02x ch=%d ip=%s\n",
           myName ? myName : '?',
           me[0], me[1], me[2], me[3], me[4], me[5],
           WiFi.channel(),
           WiFi.localIP().toString().c_str());
  broadcast(hdr);

  // ── CSI config ──────────────────────────────────────────────────────────
  wifi_csi_config_t cfg = {};
  cfg.lltf_en        = true;
  cfg.htltf_en       = false;
  cfg.stbc_htltf2_en = false;
  cfg.ltf_merge_en   = true;
  cfg.channel_filter_en = false;
  cfg.manu_scale     = false;
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
  ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(onCsi, nullptr));
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));

  // ── ESP-NOW: broadcast beacons so other boards get CSI from us ──────────
  ESP_ERROR_CHECK(esp_now_init());
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = 0;                      // 0 = use current channel
  peer.ifidx   = WIFI_IF_STA;
  ESP_ERROR_CHECK(esp_now_add_peer(&peer));

  // Must use HT MCS0 — 802.11b (default) carries no OFDM training field.
  esp_now_rate_config_t rate = {};
  rate.phymode = WIFI_PHY_MODE_HT20;
  rate.rate    = WIFI_PHY_RATE_MCS0_LGI;
  ESP_ERROR_CHECK(esp_now_set_peer_rate_config(BCAST, &rate));
}

// ── loop ──────────────────────────────────────────────────────────────────────
void loop() {
  // ── send ESP-NOW beacon ──────────────────────────────────────────────────
  static uint32_t nextSend = 0;
  if ((int32_t)(millis() - nextSend) >= 0) {
    nextSend = millis() + SEND_MS;
    uint8_t ping = 0;
    esp_now_send(BCAST, &ping, 1);
  }

  // ── drain queue into UDP batch ───────────────────────────────────────────
  // One packet must fit one Wi-Fi frame (no IP fragments). A text line is at most
  // ~25 header + 128 × 5 chars = 665 bytes, so flush whenever the next one might not fit.
  static char batch[MAX_UDP];
  static int  batchLen = 0;

  CsiReading r;
  while (xQueueReceive(q, &r, 0) == pdTRUE) {
    lastCsiMs = millis();
    if (batchLen > MAX_UDP - MAX_LINE) {
      Serial.write(batch, batchLen);
      udp.beginPacket(hubIp, HUB_PORT);
      udp.write((const uint8_t *)batch, batchLen);
      udp.endPacket();
      batchLen = 0;
    }
    batchLen += snprintf(batch + batchLen, MAX_UDP - batchLen, "CSI-%c,%lu,%d,%u,",
                         r.tx, (unsigned long)r.ms, r.rssi, r.len);
    for (int i = 0; i < r.len; i++)
      batchLen += snprintf(batch + batchLen, MAX_UDP - batchLen, i ? " %d" : "%d", r.buf[i]);
    batch[batchLen++] = '\n';
  }

  // ── heartbeat if idle ────────────────────────────────────────────────────
  static uint32_t lastHb = 0;
  uint32_t now = millis();
  if (now - lastHb >= HEARTBEAT_MS) {
    lastHb = now;
    if (now - lastCsiMs >= HEARTBEAT_MS) {   // only if actually idle
      char hb[96];
      snprintf(hb, sizeof(hb),
               "# heartbeat board=%c ms=%lu ip=%s\n",
               myName ? myName : '?',
               (unsigned long)now,
               WiFi.localIP().toString().c_str());
      broadcast(hb);
    }
  }
}
