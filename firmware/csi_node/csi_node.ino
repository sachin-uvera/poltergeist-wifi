// Poltergeist – production CSI node firmware
// Spec: .kiro/specs/firmware_csi_node.md
//
// All 4 boards run this sketch. Each board:
//   1. Joins the home router on 2.4 GHz (data pipe only).
//   2. Broadcasts tiny ESP-NOW frames so other boards get CSI from it.
//   3. Collects CSI from every other board's frame.
//   4. Batches readings (≤1400 bytes) and sends them to the hub by UDP.
//
// UDP / Serial line formats:
//   # board <X> mac <xx:xx:xx:xx:xx:xx> ch=<n> ip=<ip>   – boot announcement (R1)
//   CSI-<tx>,<ms>,<rssi>,<len>,<v0> <v1> …               – one per CSI reading (R2)
//   # heartbeat board=<X> ms=<ms> ip=<ip>                 – idle every 5 s (R3)
//   # wifi lost, reconnecting / # wifi reconnected         – reconnect events (R4)

#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_wifi.h"
#include "esp_mac.h"
#include "esp_now.h"

#if __has_include("secrets.h")
#include "secrets.h"   // defines WIFI_SSID, WIFI_PASS, HUB_IP, HUB_PORT (gitignored)
#else
#error "Copy secrets.h.example to secrets.h and fill in WIFI_SSID, WIFI_PASS, HUB_IP, HUB_PORT"
#endif

// ── Constants ────────────────────────────────────────────────────────────────

constexpr uint32_t SEND_MS      = 30;    // ESP-NOW beacon interval → ≈33 Hz per board (R7)
constexpr uint32_t HEARTBEAT_MS = 5000;  // idle threshold for heartbeat line (R3)
constexpr int      CSI_MAX      = 128;   // LLTF: 64 subcarriers × (imag, real)
constexpr int      QUEUE_DEPTH  = 64;    // drop rather than block Wi-Fi task (R6)
constexpr int      MAX_UDP      = 1400;  // fits one Wi-Fi frame (MTU 1500 minus headers) (R6)
constexpr int      MAX_LINE     = 700;   // worst-case line: header + 128 × " -128"

// ── Known boards (R8) ────────────────────────────────────────────────────────

static const uint8_t BOARDS[][6] = {
  {0x20, 0x9b, 0xa9, 0x60, 0xe1, 0x6c},  // A  CH9102
  {0x8c, 0x94, 0xdf, 0x61, 0x43, 0xb8},  // B  CH9102
  {0x8c, 0x94, 0xdf, 0x90, 0x59, 0xdc},  // C  CP210x
  {0x00, 0x70, 0x07, 0xa3, 0xdb, 0x18},  // D  CP210x
};
static const uint8_t BCAST[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

// ── Types ────────────────────────────────────────────────────────────────────

struct CsiReading {
  uint32_t ms;
  char     tx;
  int8_t   rssi;
  uint16_t len;
  int8_t   buf[CSI_MAX];
};

// ── Globals ──────────────────────────────────────────────────────────────────

static QueueHandle_t csiQueue;
static WiFiUDP       udp;
static IPAddress     hubIp;
static char          myName    = '?';
static uint32_t      lastCsiMs = 0;

// ── Helpers ──────────────────────────────────────────────────────────────────

static char boardName(const uint8_t *mac) {
  for (int i = 0; i < 4; i++)
    if (memcmp(mac, BOARDS[i], 6) == 0) return 'A' + i;
  return 0;
}

// Send a null-terminated string to both Serial and UDP (R1, R3, R4).
static void broadcast(const char *s) {
  Serial.print(s);
  udp.beginPacket(hubIp, HUB_PORT);
  udp.write((const uint8_t *)s, strlen(s));
  udp.endPacket();
}

// ── CSI callback (Wi-Fi task — copy only, never print) ───────────────────────

static void onCsi(void *, wifi_csi_info_t *info) {
  if (!info || !info->buf) return;
  char tx = boardName(info->mac);
  if (!tx) return;            // unknown sender
  if (tx == myName) return;   // ignore own reflections

  CsiReading r;
  r.ms   = millis();
  r.tx   = tx;
  r.rssi = info->rx_ctrl.rssi;
  r.len  = (info->len > CSI_MAX) ? CSI_MAX : info->len;
  memcpy(r.buf, info->buf, r.len);
  xQueueSend(csiQueue, &r, 0);  // drop if full — never block (R6)
}

// ── Wi-Fi connect (blocks until connected) ───────────────────────────────────

static void wifiConnect() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // power save makes CSI bursty (R10)
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("# connecting to " WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();
}

// ── CSI enable ───────────────────────────────────────────────────────────────

static void csiStart() {
  wifi_csi_config_t cfg = {};
  cfg.lltf_en           = true;   // LLTF only (R9)
  cfg.htltf_en          = false;
  cfg.stbc_htltf2_en    = false;
  cfg.ltf_merge_en      = true;
  cfg.channel_filter_en = false;
  cfg.manu_scale        = false;
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
  ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(onCsi, nullptr));
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

// ── ESP-NOW init ─────────────────────────────────────────────────────────────

static void espNowStart() {
  ESP_ERROR_CHECK(esp_now_init());
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = 0;         // use current channel
  peer.ifidx   = WIFI_IF_STA;
  ESP_ERROR_CHECK(esp_now_add_peer(&peer));

  // Must use HT MCS0 — 802.11b carries no OFDM training field → no CSI (R7)
  esp_now_rate_config_t rate = {};
  rate.phymode = WIFI_PHY_MODE_HT20;
  rate.rate    = WIFI_PHY_RATE_MCS0_LGI;
  ESP_ERROR_CHECK(esp_now_set_peer_rate_config(BCAST, &rate));
}

// ── setup ────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(921600);
  csiQueue = xQueueCreate(QUEUE_DEPTH, sizeof(CsiReading));

  wifiConnect();

  // Identify this board by its own MAC (R8)
  uint8_t me[6];
  esp_read_mac(me, ESP_MAC_WIFI_STA);
  myName = boardName(me);

  hubIp.fromString(HUB_IP);
  udp.begin(HUB_PORT);

  // R1: boot announcement to Serial and UDP
  char hdr[128];
  snprintf(hdr, sizeof(hdr),
           "# board %c mac %02x:%02x:%02x:%02x:%02x:%02x ch=%d ip=%s\n",
           myName ? myName : '?',
           me[0], me[1], me[2], me[3], me[4], me[5],
           WiFi.channel(),
           WiFi.localIP().toString().c_str());
  broadcast(hdr);

  csiStart();
  espNowStart();
}

// ── loop ─────────────────────────────────────────────────────────────────────

void loop() {
  // ── Reconnect if Wi-Fi dropped (R4) ────────────────────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    broadcast("# wifi lost, reconnecting\n");
    esp_now_deinit();
    ESP_ERROR_CHECK(esp_wifi_set_csi(false));

    wifiConnect();

    // Re-resolve hub IP (DHCP may have changed it) and restart
    hubIp.fromString(HUB_IP);
    csiStart();
    espNowStart();
    broadcast("# wifi reconnected\n");
    return;
  }

  // ── Send ESP-NOW beacon so other boards get CSI from us (R7) ───────────────
  static uint32_t nextSend = 0;
  if ((int32_t)(millis() - nextSend) >= 0) {
    nextSend = millis() + SEND_MS;
    uint8_t ping = 0;
    esp_now_send(BCAST, &ping, 1);
  }

  // ── Drain CSI queue into UDP batch (R6) ────────────────────────────────────
  static char  batch[MAX_UDP];
  static int   batchLen = 0;

  CsiReading r;
  while (xQueueReceive(csiQueue, &r, 0) == pdTRUE) {
    lastCsiMs = millis();

    // Flush if adding this line would exceed the frame budget
    if (batchLen > MAX_UDP - MAX_LINE) {
      Serial.write(batch, batchLen);
      udp.beginPacket(hubIp, HUB_PORT);
      udp.write((const uint8_t *)batch, batchLen);
      udp.endPacket();
      batchLen = 0;
    }

    // R2: CSI-<tx> line
    batchLen += snprintf(batch + batchLen, MAX_UDP - batchLen,
                         "CSI-%c,%lu,%d,%u,",
                         r.tx, (unsigned long)r.ms, (int)r.rssi, (unsigned)r.len);
    for (int i = 0; i < r.len; i++)
      batchLen += snprintf(batch + batchLen, MAX_UDP - batchLen,
                           i ? " %d" : "%d", (int)r.buf[i]);
    batch[batchLen++] = '\n';
  }

  // Flush any remaining lines
  if (batchLen > 0) {
    Serial.write(batch, batchLen);
    udp.beginPacket(hubIp, HUB_PORT);
    udp.write((const uint8_t *)batch, batchLen);
    udp.endPacket();
    batchLen = 0;
  }

  // ── Heartbeat if idle for 5 s (R3) ─────────────────────────────────────────
  static uint32_t lastHb = 0;
  uint32_t now = millis();
  if (now - lastHb >= HEARTBEAT_MS && now - lastCsiMs >= HEARTBEAT_MS) {
    lastHb = now;
    char hb[96];
    snprintf(hb, sizeof(hb),
             "# heartbeat board=%c ms=%lu ip=%s\n",
             myName ? myName : '?',
             (unsigned long)now,
             WiFi.localIP().toString().c_str());
    broadcast(hb);
  }
}
