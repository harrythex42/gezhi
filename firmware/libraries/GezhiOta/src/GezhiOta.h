#pragma once

namespace GezhiOta {
// Replaces Serial.begin. Sketches may write to Serial but must not read it.
void begin(unsigned long baud);
// Call early in loop(). Returns immediately unless an upload starts.
void poll();
}
