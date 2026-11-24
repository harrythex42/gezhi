#include "GezhiOta.h"

#include <Arduino.h>
#include <Update.h>
#include <ctype.h>
#include <stdlib.h>

namespace {
constexpr size_t BLOCK_SIZE = 1024;
constexpr uint32_t TIMEOUT_MS = 5000;
constexpr char COMMAND[] = "GZOTA1 ";
constexpr char CAPABLE[] = "GZOTA1-CAPABLE";
uint8_t block[BLOCK_SIZE];
char line[64];
size_t lineSize = 0;
bool discardLine = false;
uint32_t lastByte = 0;

void fail(const char *reason) {
  if (Update.isRunning()) Update.abort();
  Serial.printf("GZOTA ERR %s\n", reason);
}

bool receiveBlock(size_t count) {
  uint32_t last = millis();
  for (size_t got = 0; got < count;) {
    size_t n = Serial.read(block + got, count - got);
    if (n) {
      got += n;
      last = millis();
    } else {
      if (millis() - last >= TIMEOUT_MS) return false;
      delay(1);
    }
  }
  return true;
}

void upload(char *args) {
  char *end;
  const unsigned long size = strtoul(args, &end, 10);
  if (*args < '0' || *args > '9' || *end != ' ' || !size || size == UPDATE_SIZE_UNKNOWN) {
    fail("invalid size");
    return;
  }
  const char *md5 = end + 1;
  if (strlen(md5) != 32 || strspn(md5, "0123456789abcdefABCDEF") != 32) {
    fail("invalid MD5");
    return;
  }
  if (!Update.begin(size, U_FLASH) || !Update.setMD5(md5)) {
    fail(Update.errorString());
    return;
  }

  Serial.printf("GZOTA READY %u %s\n", (unsigned)BLOCK_SIZE, CAPABLE);
  for (size_t total = 0; total < size;) {
    const size_t count = min(BLOCK_SIZE, (size_t)size - total);
    if (!receiveBlock(count)) {
      fail("timeout receiving block");
      return;
    }
    if (Update.write(block, count) != count || Update.hasError()) {
      fail(Update.errorString());
      return;
    }
    total += count;
    Serial.printf("GZOTA ACK %u\n", (unsigned)total);
  }
  // All declared bytes arrived. end() checks MD5 and validates the boot image.
  if (!Update.end(true)) {
    fail(Update.errorString());
    return;
  }
  Serial.println("GZOTA DONE");
  Serial.flush();
  ESP.restart();
}
}

void GezhiOta::begin(unsigned long baud) {
  Serial.setRxBufferSize(8192);
  Serial.begin(baud);
}

void GezhiOta::poll() {
  if ((lineSize || discardLine) && millis() - lastByte >= TIMEOUT_MS) {
    if (lineSize >= sizeof(COMMAND) - 1 && !strncmp(line, COMMAND, sizeof(COMMAND) - 1))
      fail("timeout receiving command");
    lineSize = 0;
    discardLine = false;
  }
  for (unsigned i = 0; i < 128 && Serial.available(); ++i) {
    int ch = Serial.read();
    lastByte = millis();
    if (ch == '\n') {
      line[lineSize] = '\0';
      bool isCommand = !discardLine && !strncmp(line, COMMAND, sizeof(COMMAND) - 1);
      lineSize = 0;
      discardLine = false;
      if (isCommand) {
        upload(line + sizeof(COMMAND) - 1);
        return;
      }
    } else if (ch >= 0 && ch != '\r' && !discardLine) {
      if (lineSize < sizeof(line) - 1) line[lineSize++] = ch;
      else discardLine = true;
    }
  }
}
