#include "audio_capture.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>

#include "esp_log.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"

namespace {
constexpr gpio_num_t kBclkPin = GPIO_NUM_11;
constexpr gpio_num_t kWsPin = GPIO_NUM_10;
constexpr gpio_num_t kDataPin = GPIO_NUM_12;
constexpr const char* kTag = "AUDIO_CAPTURE";
}

esp_err_t AudioCapture::Init() {
    i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    ESP_RETURN_ON_ERROR(i2s_new_channel(&channel_config, nullptr, &channel_), kTag, "i2s_new_channel");

    i2s_std_config_t config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(kSampleRate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = kBclkPin,
            .ws = kWsPin,
            .dout = I2S_GPIO_UNUSED,
            .din = kDataPin,
            .invert_flags = {},
        },
    };
    config.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(channel_, &config), kTag, "i2s init");
    ESP_RETURN_ON_ERROR(i2s_channel_enable(channel_), kTag, "i2s enable");
    ESP_LOGI(kTag, "INMP441: BCLK=%d WS=%d SD=%d shift=%d", kBclkPin, kWsPin, kDataPin, kI2sToPcmShift);
    return ESP_OK;
}

esp_err_t AudioCapture::ReadPcm16(int16_t* destination, size_t capacity, size_t* samples_read) {
    if (channel_ == nullptr || destination == nullptr || samples_read == nullptr || capacity == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    int32_t raw[320];
    const size_t requested = std::min(capacity, sizeof(raw) / sizeof(raw[0]));
    size_t bytes_read = 0;
    ESP_RETURN_ON_ERROR(
        i2s_channel_read(channel_, raw, requested * sizeof(raw[0]), &bytes_read, portMAX_DELAY),
        kTag,
        "i2s read");

    const size_t count = bytes_read / sizeof(raw[0]);
    int64_t sum_squares = 0;
    int32_t peak = 0;
    for (size_t index = 0; index < count; ++index) {
        const int32_t shifted = raw[index] >> kI2sToPcmShift;
        const int32_t clamped = std::clamp(shifted, int32_t{-32768}, int32_t{32767});
        destination[index] = static_cast<int16_t>(clamped);
        const int32_t magnitude = std::abs(clamped);
        peak = std::max(peak, magnitude);
        sum_squares += static_cast<int64_t>(clamped) * clamped;
    }
    const float rms = count == 0 ? 0.0f : std::sqrt(static_cast<float>(sum_squares) / count) / 32768.0f;
    last_level_ = AudioLevel{.rms_dbfs = rms > 0.0f ? 20.0f * std::log10(rms) : -120.0f,
                             .peak = static_cast<int16_t>(std::min(peak, int32_t{32767}))};
    *samples_read = count;
    return ESP_OK;
}
