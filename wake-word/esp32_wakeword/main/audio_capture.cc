#include "audio_capture.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>

#include "device_pins.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_attr.h"
#include "freertos/FreeRTOS.h"

namespace {
constexpr gpio_num_t kBclkPin = static_cast<gpio_num_t>(DevicePins::kMicBclk);
constexpr gpio_num_t kWsPin = static_cast<gpio_num_t>(DevicePins::kMicWs);
constexpr gpio_num_t kDataPin = static_cast<gpio_num_t>(DevicePins::kMicSd);
constexpr const char *kTag = "AUDIO_CAPTURE";
} // namespace

esp_err_t AudioCapture::Init() {
    i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    ESP_RETURN_ON_ERROR(i2s_new_channel(&channel_config, nullptr, &channel_), kTag, "i2s_new_channel");

    i2s_std_config_t config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(kSampleRate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg =
            {
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
    i2s_event_callbacks_t callbacks = {};
    callbacks.on_recv_q_ovf = OnOverflow;
    ESP_RETURN_ON_ERROR(i2s_channel_register_event_callback(channel_, &callbacks, this), kTag, "i2s callback");
    ESP_RETURN_ON_ERROR(i2s_channel_enable(channel_), kTag, "i2s enable");
    ESP_LOGI(kTag, "INMP441: BCLK=%d WS=%d SD=%d shift=%d", kBclkPin, kWsPin, kDataPin, kI2sToPcmShift);
    constexpr size_t kQueueFrames = 64;
    queue_storage_ = static_cast<uint8_t *>(
        heap_caps_malloc(kQueueFrames * sizeof(Frame), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (queue_storage_ == nullptr)
        return ESP_ERR_NO_MEM;
    frames_ = xQueueCreateStatic(kQueueFrames, sizeof(Frame), queue_storage_, &queue_control_);
    if (xTaskCreatePinnedToCore(CaptureEntry, "inmp441_capture", kCaptureStackBytes, this, 6, &task_, 0) != pdPASS) {
        vQueueDelete(frames_);
        frames_ = nullptr;
        heap_caps_free(queue_storage_);
        queue_storage_ = nullptr;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

esp_err_t AudioCapture::ReadPcm16(int16_t *destination, size_t capacity, size_t *samples_read) {
    if (channel_ == nullptr || destination == nullptr || samples_read == nullptr || capacity == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (frames_ == nullptr || capacity < 320)
        return ESP_ERR_INVALID_SIZE;
    Frame frame;
    if (xQueueReceive(frames_, &frame, pdMS_TO_TICKS(2000)) != pdTRUE)
        return ESP_ERR_TIMEOUT;
    std::memcpy(destination, frame.samples, frame.count * sizeof(int16_t));
    last_level_ = frame.level;
    last_sequence_ = frame.sequence;
    last_timestamp_ms_ = frame.timestamp_ms;
    last_loss_epoch_ = frame.loss_epoch;
    *samples_read = frame.count;
    return ESP_OK;
}

void AudioCapture::CaptureEntry(void *context) { static_cast<AudioCapture *>(context)->RunCapture(); }

bool IRAM_ATTR AudioCapture::OnOverflow(i2s_chan_handle_t, i2s_event_data_t*, void* context) {
    auto* self = static_cast<AudioCapture*>(context);
    portENTER_CRITICAL_ISR(&self->loss_mux_);
    ++self->loss_epoch_;
    portEXIT_CRITICAL_ISR(&self->loss_mux_);
    return false;
}

uint32_t AudioCapture::LossEpoch() {
    portENTER_CRITICAL(&loss_mux_);
    const uint32_t epoch = loss_epoch_;
    portEXIT_CRITICAL(&loss_mux_);
    return epoch;
}

void AudioCapture::MarkLoss() {
    portENTER_CRITICAL(&loss_mux_);
    ++loss_epoch_;
    portEXIT_CRITICAL(&loss_mux_);
}

void AudioCapture::RunCapture() {
    auto& raw = raw_samples_;
    Frame& frame = capture_frame_;
    Frame& discarded = discarded_frame_;
    uint32_t sequence = 0;
    uint32_t drops = 0;
    while (true) {
        size_t bytes_read = 0;
        const uint32_t before_read = LossEpoch();
        const esp_err_t result = i2s_channel_read(channel_, raw, sizeof(raw), &bytes_read, 1000);
        if (result != ESP_OK) {
            MarkLoss();
            ESP_LOGW(kTag, "i2s read: %s", esp_err_to_name(result));
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        const size_t count = bytes_read / sizeof(raw[0]);
        if (count == 0 || bytes_read % sizeof(raw[0]) != 0) {
            MarkLoss();
            continue;
        }
        const uint32_t after_read = LossEpoch();
        if (after_read != before_read) {
            ESP_LOGW(kTag, "Perda I2S/DMA detectada; bloco descartado");
            continue;
        }
        int64_t sum_squares = 0;
        int32_t peak = 0;
        for (size_t index = 0; index < count; ++index) {
            const int32_t shifted = raw[index] >> kI2sToPcmShift;
            const int32_t clamped = std::clamp(shifted, int32_t{-32768}, int32_t{32767});
            frame.samples[index] = static_cast<int16_t>(clamped);
            const int32_t magnitude = std::abs(clamped);
            peak = std::max(peak, magnitude);
            sum_squares += static_cast<int64_t>(clamped) * clamped;
        }
        const float rms = count == 0 ? 0.0f : std::sqrt(static_cast<float>(sum_squares) / count) / 32768.0f;
        frame.level = AudioLevel{.rms_dbfs = rms > 0.0f ? 20.0f * std::log10(rms) : -120.0f,
                                 .peak = static_cast<int16_t>(std::min(peak, int32_t{32767}))};
        frame.count = count;
        frame.sequence = ++sequence;
        frame.loss_epoch = after_read;
        frame.timestamp_ms = esp_timer_get_time() / 1000;
        if (xQueueSend(frames_, &frame, 0) != pdTRUE) {
            // Preserve recent audio and make the gap visible to the consumer.
            xQueueReceive(frames_, &discarded, 0);
            xQueueSend(frames_, &frame, 0);
            if (++drops % 50 == 1)
                ESP_LOGW(kTag, "Fila de audio atrasada: %lu blocos descartados",
                         static_cast<unsigned long>(drops));
        }
    }
}
