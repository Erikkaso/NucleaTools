#pragma once
#include "sdkconfig.h"

namespace DevicePins {
constexpr int kMicBclk = CONFIG_NUCLEA_MIC_BCLK_GPIO;
constexpr int kMicWs = CONFIG_NUCLEA_MIC_WS_GPIO;
constexpr int kMicSd = CONFIG_NUCLEA_MIC_SD_GPIO;
constexpr int kLcdClock = 4;
constexpr int kLcdMosi = 5;
constexpr int kLcdCs = 15;
constexpr int kLcdDc = 7;
constexpr int kLcdReset = 6;
constexpr bool SafeMicPin(int pin) {
    // Exclude USB, flash/OPI PSRAM, strapping, unavailable GPIOs and RGB LED.
    return (pin >= 1 && pin <= 18 && pin != 3) || pin == 21 ||
           (pin >= 38 && pin <= 47 && pin != 45 && pin != 46);
}
static_assert(SafeMicPin(kMicBclk) && SafeMicPin(kMicWs) && SafeMicPin(kMicSd),
              "Use exposed microphone GPIOs, not USB/flash/PSRAM/strapping/LED pins");
static_assert(kMicBclk != kMicWs && kMicBclk != kMicSd && kMicWs != kMicSd,
              "Microphone GPIOs must be distinct");
#if defined(CONFIG_NUCLEA_DISPLAY_ENABLED) && !defined(CONFIG_NUCLEA_DISPLAY_ONLY_TEST)
constexpr bool IsLcdPin(int pin) {
    return pin == kLcdClock || pin == kLcdMosi || pin == kLcdCs ||
           pin == kLcdDc || pin == kLcdReset;
}
static_assert(!IsLcdPin(kMicBclk) && !IsLcdPin(kMicWs) && !IsLcdPin(kMicSd),
              "Microphone GPIO conflicts with ST7789; use 41/42/40 or disable display");
#endif
#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
constexpr int kSpeakerBclk = CONFIG_NUCLEA_SPEAKER_BCLK_GPIO;
constexpr int kSpeakerWs = CONFIG_NUCLEA_SPEAKER_WS_GPIO;
constexpr int kSpeakerData = CONFIG_NUCLEA_SPEAKER_DIN_GPIO;
#ifndef CONFIG_NUCLEA_DISPLAY_ONLY_TEST
constexpr bool SafeSpeakerPin(int pin) {
    return SafeMicPin(pin) && pin != kMicBclk && pin != kMicWs && pin != kMicSd;
}
static_assert(SafeSpeakerPin(kSpeakerBclk) && SafeSpeakerPin(kSpeakerWs) && SafeSpeakerPin(kSpeakerData),
              "Speaker GPIO conflicts with microphone or reserved pins");
static_assert(kSpeakerBclk != kSpeakerWs && kSpeakerBclk != kSpeakerData && kSpeakerWs != kSpeakerData,
              "Speaker GPIOs must be distinct");
#ifdef CONFIG_NUCLEA_DISPLAY_ENABLED
static_assert(!IsLcdPin(kSpeakerBclk) && !IsLcdPin(kSpeakerWs) && !IsLcdPin(kSpeakerData),
              "Speaker GPIO conflicts with ST7789");
#endif
#endif
#endif
}
