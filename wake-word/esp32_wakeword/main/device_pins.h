#pragma once
#include "sdkconfig.h"

namespace DevicePins {
constexpr int kMicBclk = CONFIG_NUCLEA_MIC_BCLK_GPIO;
constexpr int kMicWs = CONFIG_NUCLEA_MIC_WS_GPIO;
constexpr int kMicSd = CONFIG_NUCLEA_MIC_SD_GPIO;
constexpr int kLcdClock = 10;
constexpr int kLcdMosi = 11;
constexpr int kLcdCs = 12;
constexpr int kLcdDc = 9;
constexpr int kLcdReset = 8;
constexpr bool SafeMicPin(int pin) {
    // Exclude USB, flash/OPI PSRAM, strapping, unavailable GPIOs and RGB LED.
    return (pin >= 1 && pin <= 18 && pin != 3) || pin == 21 ||
           (pin >= 38 && pin <= 47 && pin != 45 && pin != 46);
}
static_assert(SafeMicPin(kMicBclk) && SafeMicPin(kMicWs) && SafeMicPin(kMicSd),
              "Use exposed microphone GPIOs, not USB/flash/PSRAM/strapping/LED pins");
static_assert(kMicBclk != kMicWs && kMicBclk != kMicSd && kMicWs != kMicSd,
              "Microphone GPIOs must be distinct");
#ifdef CONFIG_NUCLEA_DISPLAY_ENABLED
constexpr bool IsLcdPin(int pin) { return pin >= 8 && pin <= 12; }
static_assert(!IsLcdPin(kMicBclk) && !IsLcdPin(kMicWs) && !IsLcdPin(kMicSd),
              "Microphone GPIO conflicts with ST7789; rewire to 4/5/6 or disable display");
#endif
}
