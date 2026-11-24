// MPU6050: VCC 3V3, GND. ESP32-S3: SDA 8, SCL 9. ESP32: SDA 21, SCL 22.
#include <Wire.h>
#include <phyphoxBle.h>
#include <GezhiOta.h>
#include <atomic>
#include <math.h>

#if CONFIG_IDF_TARGET_ESP32S3
const int SDA_PIN = 8, SCL_PIN = 9;
#else
const int SDA_PIN = 21, SCL_PIN = 22;
#endif

const char BLE_NAME[] = "Gezhi-IMU";
const unsigned IMU_VERSION = 2;
const uint32_t FRAME_MS = 20;
const uint32_t SCAN_MS = 3000;
const uint32_t OTA_HEAD_START_MS = 3500;
enum BleState { Waiting, Starting, Ready, Failed };
std::atomic<BleState> bleState{Waiting};
uint8_t mpuAddr = 0;
uint32_t startMs, lastScan, lastFrame, lastSummary;
unsigned frames = 0, accepted = 0, refused = 0;

bool writeReg(uint8_t addr, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readRegs(uint8_t addr, uint8_t reg, uint8_t *buf, size_t count) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, count) != count) return false;
  for (size_t i = 0; i < count; ++i) buf[i] = Wire.read();
  return true;
}

void scanMpu() {
  lastScan = millis();
  Serial.println("I2C scan: 0x68 / 0x69");
  for (uint8_t addr = 0x68; addr <= 0x69; ++addr) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() != 0) continue;
    uint8_t who;
    // Log the ID but accept register-compatible parts with other IDs.
    if (readRegs(addr, 0x75, &who, 1))
      Serial.printf("  Found 0x%02X, WHO_AM_I=0x%02X\n", addr, who);
    else
      Serial.printf("  Found 0x%02X, WHO_AM_I read failed\n", addr);
    if (!writeReg(addr, 0x6B, 0x00) ||  // Wake up
        !writeReg(addr, 0x1A, 0x03) ||  // DLPF ~44 Hz
        !writeReg(addr, 0x1C, 0x10)) {  // +/-8 g
      Serial.println("  MPU configuration failed");
      continue;
    }
    mpuAddr = addr;
    Serial.println("Mode: MPU");
    return;
  }
  Serial.println("  No usable MPU found; mode: test signal (测试信号)");
}

bool readAccel(float &ax, float &ay, float &az) {
  uint8_t b[6];
  if (!readRegs(mpuAddr, 0x3B, b, sizeof(b))) return false;
  auto g = [&](int i) { return (int16_t)((b[i] << 8) | b[i + 1]) / 4096.0f; };
  ax = g(0);
  ay = g(2);
  az = g(4);
  return true;
}

bool startBle() {
  Serial.println("BLE init: build experiment");
  PhyphoxBleExperiment experiment;
  experiment.setTitle("格致 · 加速度");
  experiment.setCategory("格致 Gezhi");
  experiment.setDescription("MPU6050 acceleration. Sine-wave test signal if no sensor is connected.");

  PhyphoxBleExperiment::View view;
  view.setLabel("加速度");
  PhyphoxBleExperiment::Graph magnitude, axes;
  magnitude.setLabel("|a|");
  magnitude.setLabelX("t");
  magnitude.setUnitX("s");
  magnitude.setLabelY("|a|");
  magnitude.setUnitY("g");
  magnitude.setChannel(1, 5);
  axes.setLabel("ax (red), ay (green), az (blue)");
  axes.setLabelX("t");
  axes.setUnitX("s");
  axes.setLabelY("a");
  axes.setUnitY("g");
  axes.setChannel(1, 2);
  axes.setColor(COLOR_RED);
  PhyphoxBleExperiment::Graph::Subgraph y, z;
  y.setChannel(1, 3);
  y.setColor(COLOR_GREEN);
  z.setChannel(1, 4);
  z.setColor(COLOR_BLUE);
  axes.addSubgraph(y);
  axes.addSubgraph(z);
  view.addElement(magnitude);
  view.addElement(axes);
  experiment.addView(view);

  PhyphoxBleExperiment::ExportSet exportSet;
  exportSet.setLabel("Acceleration");
  const char *labels[] = {"t (s)", "ax (g)", "ay (g)", "az (g)", "|a| (g)"};
  for (int i = 0; i < 5; ++i) {
    PhyphoxBleExperiment::ExportData column;
    column.setLabel(labels[i]);
    column.setDatachannel(i + 1);
    exportSet.addElement(column);
  }
  experiment.addExportSet(exportSet);
  Serial.println("BLE init: add experiment");
  PhyphoxBLE::server().setDeviceName(BLE_NAME);
  PhyphoxBLE::addExperiment(experiment);
  Serial.println("BLE init: start transport");
  PhyphoxBLE::start(BLE_NAME);
  PhyphoxBLE::poll();
  const bool ok = PhyphoxBLE::server().started();
  Serial.printf("BLE: %s (%s)\n", BLE_NAME,
                ok ? "started" : "start failed");
  PhyphoxBLE::printErrors(&Serial);
  return ok;
}

void startBleTask(void *) {
  bleState.store(startBle() ? Ready : Failed);
  vTaskDelete(nullptr);
}

void setup() {
  GezhiOta::begin(115200);
}

void loop() {
  GezhiOta::poll();
  static bool started = false;
  if (!started) {
    if (millis() < 1500) {
      delay(1);
      return;  // Let USB serial attach after reset.
    }
    Serial.printf("\n=== Gezhi IMU / phyphox BLE v%u ===\n", IMU_VERSION);
    Serial.println("OTA: ready; BLE starts after the recovery window");
    Serial.printf("SDA=%d SCL=%d\n", SDA_PIN, SCL_PIN);
    Wire.begin(SDA_PIN, SCL_PIN, 400000);
    Wire.setTimeOut(5);
    scanMpu();
    startMs = lastFrame = lastSummary = millis();
    started = true;
  }

  // Keep OTA and sampling in loop(), even if the BLE stack never comes back.
  BleState state = bleState.load();
  if (state == Waiting && millis() - startMs >= OTA_HEAD_START_MS) {
    bleState.store(Starting);
    state = Starting;
    if (xTaskCreate(startBleTask, "GezhiBleInit", 8192, nullptr, 1, nullptr) != pdPASS) {
      Serial.println("BLE init: cannot allocate task");
      bleState.store(Failed);
    }
  }
  if (state == Ready) PhyphoxBLE::poll();
  if (!mpuAddr && millis() - lastScan >= SCAN_MS) scanMpu();
  uint32_t now = millis();
  uint32_t elapsed = now - lastFrame;
  if (elapsed < FRAME_MS) {
    delay(1);
    return;
  }
  lastFrame += elapsed - elapsed % FRAME_MS;  // Skip missed ticks, no bursts.

  float t = (now - startMs) * 0.001f;
  float ax, ay, az;
  if (mpuAddr && !readAccel(ax, ay, az)) {
    Serial.println("MPU read failed; mode: test signal (测试信号)");
    mpuAddr = 0;
    lastScan = now;
  }
  if (!mpuAddr) {
    ax = sinf(PI * t);
    ay = 0.0f;
    az = 1.0f;
  }
  float magnitude = sqrtf(ax * ax + ay * ay + az * az);
  if (state == Ready && PhyphoxBLE::isSubscribed) {
    uint32_t before = PhyphoxBLE::stats().dataRefused;
    PhyphoxBLE::write(t, ax, ay, az, magnitude);
    if (PhyphoxBLE::stats().dataRefused == before) ++accepted;
    else ++refused;
  }
  ++frames;
  if (now - lastSummary >= 1000) {
    Serial.printf("mode=%s frames=%u |a|=%.3f g ble=%s accepted=%u refused=%u\n",
                  mpuAddr ? "MPU" : "test signal", frames, magnitude,
                  state == Ready ? "ready" : state == Failed ? "failed" :
                  state == Starting ? "starting" : "waiting",
                  accepted, refused);
    frames = accepted = refused = 0;
    lastSummary = now;
  }
}
