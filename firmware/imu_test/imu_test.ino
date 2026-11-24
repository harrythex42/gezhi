// Step 1 bring-up: RGB LED blink, I2C scan, then raw MPU6050 readings.
// Wiring: MPU6050 VCC -> 3V3, GND -> GND
//   ESP32-S3: SDA -> GPIO8,  SCL -> GPIO9
//   ESP32:    SDA -> GPIO21, SCL -> GPIO22
#include <Wire.h>
#include <GezhiOta.h>

#if CONFIG_IDF_TARGET_ESP32S3
const int SDA_PIN = 8;
const int SCL_PIN = 9;
const int RGB_PIN = 48;  // DevKitC-1 v1.0; some v1.1 boards use 38
#else
const int SDA_PIN = 21;
const int SCL_PIN = 22;
const int RGB_PIN = -1;  // no RGB LED
#endif
const int IMU_VERSION = 4;
uint8_t mpuAddr = 0;

void writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool readRegs(uint8_t reg, uint8_t *buf, size_t n) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(mpuAddr, (uint8_t)n) != n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

void scanI2C() {
  Serial.println("I2C scan:");
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf("  found device at 0x%02X\n", a);
      if (a == 0x68 || a == 0x69) mpuAddr = a;
      found++;
    }
  }
  if (!found) Serial.println("  nothing found - check wiring (SDA/SCL, VCC=3V3)");
}

void setup() {
  GezhiOta::begin(115200);
  delay(1500);  // give the USB serial time to attach
  for (int i = 0; RGB_PIN >= 0 && i < 3; i++) {
    rgbLedWrite(RGB_PIN, 0, 40, 0);
    delay(150);
    rgbLedWrite(RGB_PIN, 0, 0, 0);
    delay(150);
  }
  Serial.printf("\n=== IMU test v%d (SDA=%d, SCL=%d) ===\n", IMU_VERSION, SDA_PIN, SCL_PIN);
  Wire.begin(SDA_PIN, SCL_PIN, 400000);
  scanI2C();
  if (!mpuAddr) return;

  uint8_t who = 0;
  readRegs(0x75, &who, 1);
  // 0x68 = genuine MPU6050; clones often report 0x70/0x72/0x98 etc. They still work.
  Serial.printf("MPU at 0x%02X, WHO_AM_I = 0x%02X\n", mpuAddr, who);
  writeReg(0x6B, 0x00);  // wake up
  writeReg(0x1A, 0x03);  // digital low-pass ~44 Hz
  writeReg(0x1B, 0x08);  // gyro +-500 deg/s
  writeReg(0x1C, 0x10);  // accel +-8 g
  delay(100);
  Serial.println("ax(g)\tay(g)\taz(g)\t|a|(g)\tgx\tgy\tgz (deg/s)");
}

void loop() {
  GezhiOta::poll();
  static uint32_t last = 0;
  if (!mpuAddr) {
    if (millis() - last > 3000) { last = millis(); scanI2C(); }
    return;
  }
  if (millis() - last < 50) return;  // 20 Hz
  last = millis();
  uint8_t b[14];
  if (!readRegs(0x3B, b, 14)) { Serial.println("read failed"); return; }
  auto s16 = [&](int i) { return (int16_t)((b[i] << 8) | b[i + 1]); };
  float ax = s16(0) / 4096.0f, ay = s16(2) / 4096.0f, az = s16(4) / 4096.0f;
  float gx = s16(8) / 65.5f, gy = s16(10) / 65.5f, gz = s16(12) / 65.5f;
  Serial.printf("%.3f\t%.3f\t%.3f\t%.3f\t%.1f\t%.1f\t%.1f\n",
                ax, ay, az, sqrtf(ax * ax + ay * ay + az * az), gx, gy, gz);
}
