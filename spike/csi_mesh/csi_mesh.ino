// Board-to-board spike: no router. Same sketch on all 4 boards.
// Each board broadcasts a tiny ESP-NOW packet every SEND_MS and records CSI from the other boards,
// so 4 boards give 6 links (12 directions) across the room.
// Output, one line per received packet:  CSI-<tx>,<ms>,<rssi>,<len>,<v0> <v1> ...
//   <tx> = board letter that sent it; values are interleaved imag,real, LLTF = 64 subcarriers.
#include <WiFi.h>
#include "esp_wifi.h"
#include "esp_mac.h"
#include "esp_now.h"

constexpr uint8_t CHANNEL = 6;    // all boards must match; pick the quietest 2.4 GHz channel
constexpr uint32_t SEND_MS = 30;  // ~33 Hz per board; 3 senders -> ~100 lines/s per board on serial
constexpr int CSI_MAX = 128;

// Known boards (factory MACs from esptool). Unknown senders are ignored.
static const uint8_t BOARDS[][6] = {
  {0x20, 0x9b, 0xa9, 0x60, 0xe1, 0x6c},  // A
  {0x8c, 0x94, 0xdf, 0x61, 0x43, 0xb8},  // B
  {0x8c, 0x94, 0xdf, 0x90, 0x59, 0xdc},  // C
  {0x00, 0x70, 0x07, 0xa3, 0xdb, 0x18},  // D
};
static const uint8_t BCAST[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

struct CsiPacket {
  uint32_t ms;
  char tx;
  int8_t rssi;
  uint16_t len;
  int8_t buf[CSI_MAX];
};

static QueueHandle_t q;

static char boardName(const uint8_t *mac) {
  for (int i = 0; i < 4; i++)
    if (memcmp(mac, BOARDS[i], 6) == 0) return 'A' + i;
  return 0;
}

// Runs in the Wi-Fi task: copy only, never print here.
static void onCsi(void *, wifi_csi_info_t *info) {
  if (!info || !info->buf) return;
  char tx = boardName(info->mac);
  if (!tx) return;
  CsiPacket p;
  p.ms = millis();
  p.tx = tx;
  p.rssi = info->rx_ctrl.rssi;
  p.len = info->len > CSI_MAX ? CSI_MAX : info->len;
  memcpy(p.buf, info->buf, p.len);
  xQueueSend(q, &p, 0);  // drop if full rather than block Wi-Fi
}

void setup() {
  Serial.begin(921600);
  q = xQueueCreate(32, sizeof(CsiPacket));

  WiFi.mode(WIFI_STA);  // starts Wi-Fi, never connects
  WiFi.setSleep(false);
  ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20));
  ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));  // hear every frame on the channel; onCsi filters by MAC
  ESP_ERROR_CHECK(esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE));

  uint8_t me[6];
  esp_read_mac(me, ESP_MAC_WIFI_STA);
  char name = boardName(me);
  Serial.printf("\n# board %c mac %02x:%02x:%02x:%02x:%02x:%02x ch=%d\n", name ? name : '?',
                me[0], me[1], me[2], me[3], me[4], me[5], CHANNEL);

  ESP_ERROR_CHECK(esp_now_init());
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  ESP_ERROR_CHECK(esp_now_add_peer(&peer));
  // Default ESP-NOW rate is 1 Mbps 802.11b, which carries no OFDM training field = no CSI. Send HT MCS0.
  esp_now_rate_config_t rate = {};
  rate.phymode = WIFI_PHY_MODE_HT20;
  rate.rate = WIFI_PHY_RATE_MCS0_LGI;
  ESP_ERROR_CHECK(esp_now_set_peer_rate_config(BCAST, &rate));

  wifi_csi_config_t cfg = {};
  cfg.lltf_en = true;
  cfg.ltf_merge_en = true;
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
  ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(onCsi, nullptr));
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

void loop() {
  static uint32_t next = 0;
  if ((int32_t)(millis() - next) >= 0) {
    next = millis() + SEND_MS;
    uint8_t ping = 0;
    esp_now_send(BCAST, &ping, 1);
  }
  CsiPacket p;
  if (xQueueReceive(q, &p, 1) != pdTRUE) return;
  Serial.printf("CSI-%c,%lu,%d,%u,", p.tx, (unsigned long)p.ms, p.rssi, p.len);
  for (int i = 0; i < p.len; i++) Serial.printf(i ? " %d" : "%d", p.buf[i]);
  Serial.print('\n');
}
