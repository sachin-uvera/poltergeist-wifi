// Go/no-go spike: stream Wi-Fi CSI from the home router to USB serial.
// Router mode: the board pings the gateway ~100x/s; each reply carries CSI.
// Output, one line per packet:  CSI,<ms>,<rssi>,<len>,<v0> <v1> ...
// (values are interleaved imag,real per subcarrier, LLTF only = 64 subcarriers)
#include <WiFi.h>
#include "esp_wifi.h"
#include "ping/ping_sock.h"
#include "lwip/ip_addr.h"

#if __has_include("secrets.h")
#include "secrets.h"  // defines WIFI_SSID, WIFI_PASS (gitignored)
#else
#error "Copy secrets.h.example to secrets.h and fill in your Wi-Fi name and password"
#endif

constexpr int PING_INTERVAL_MS = 10;  // ~100 Hz
constexpr int CSI_MAX = 128;          // LLTF: 64 subcarriers x (imag, real)

struct CsiPacket {
  uint32_t ms;
  int8_t rssi;
  uint16_t len;
  int8_t buf[CSI_MAX];
};

static QueueHandle_t q;
static uint8_t routerMac[6];

// Runs in the Wi-Fi task: copy only, never print here.
static void onCsi(void *, wifi_csi_info_t *info) {
  if (!info || !info->buf || memcmp(info->mac, routerMac, 6) != 0) return;
  CsiPacket p;
  p.ms = millis();
  p.rssi = info->rx_ctrl.rssi;
  p.len = info->len > CSI_MAX ? CSI_MAX : info->len;
  memcpy(p.buf, info->buf, p.len);
  xQueueSend(q, &p, 0);  // drop if full rather than block Wi-Fi
}

// Only reports on our own SSID: is it visible on 2.4 GHz, on which channel, with which security.
static void diagnose() {
  Serial.printf("\n# not connected yet, status=%d; scanning...\n", WiFi.status());
  WiFi.disconnect();  // scan fails (-2) while a connect attempt is running
  delay(100);
  int n = WiFi.scanNetworks();
  bool seen = false;
  for (int i = 0; i < n; i++) {
    if (WiFi.SSID(i) != WIFI_SSID) continue;
    seen = true;
    Serial.printf("# found SSID: ch=%d rssi=%d auth=%d\n", WiFi.channel(i), WiFi.RSSI(i), WiFi.encryptionType(i));
  }
  if (!seen) Serial.printf("# SSID not visible on 2.4 GHz (%d networks seen). 5 GHz-only name or typo?\n", n);
  WiFi.scanDelete();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("# connecting");
}

void setup() {
  Serial.begin(921600);
  q = xQueueCreate(32, sizeof(CsiPacket));

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // power save makes CSI bursty
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("# connecting");
  for (int i = 0; WiFi.status() != WL_CONNECTED; i++) {
    delay(250);
    Serial.print('.');
    if (i % 60 == 59) diagnose();  // every ~15 s, say why
  }
  memcpy(routerMac, WiFi.BSSID(), 6);
  Serial.printf("\n# connected ch=%d rssi=%d gw=%s bssid=%s\n", WiFi.channel(), WiFi.RSSI(),
                WiFi.gatewayIP().toString().c_str(), WiFi.BSSIDstr().c_str());

  wifi_csi_config_t cfg = {};
  cfg.lltf_en = true;
  cfg.htltf_en = false;
  cfg.stbc_htltf2_en = false;
  cfg.ltf_merge_en = true;
  cfg.channel_filter_en = false;
  cfg.manu_scale = false;
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
  ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(onCsi, nullptr));
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));

  ip_addr_t gw;
  ipaddr_aton(WiFi.gatewayIP().toString().c_str(), &gw);
  esp_ping_config_t pc = ESP_PING_DEFAULT_CONFIG();
  pc.target_addr = gw;
  pc.count = ESP_PING_COUNT_INFINITE;
  pc.interval_ms = PING_INTERVAL_MS;
  pc.data_size = 1;
  esp_ping_callbacks_t cbs = {};
  esp_ping_handle_t ping;
  ESP_ERROR_CHECK(esp_ping_new_session(&pc, &cbs, &ping));
  ESP_ERROR_CHECK(esp_ping_start(ping));
}

void loop() {
  CsiPacket p;
  if (xQueueReceive(q, &p, portMAX_DELAY) != pdTRUE) return;
  Serial.printf("CSI,%lu,%d,%u,", (unsigned long)p.ms, p.rssi, p.len);
  for (int i = 0; i < p.len; i++) Serial.printf(i ? " %d" : "%d", p.buf[i]);
  Serial.print('\n');
}
