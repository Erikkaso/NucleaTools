#pragma once

#include <cstddef>
#include <cstdint>

#include "driver/i2s_std.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

struct AudioLevel {
    float rms_dbfs;
    int16_t peak;
};

class AudioCapture {
public:
    esp_err_t Init();
    esp_err_t ReadPcm16(int16_t* destination, size_t capacity, size_t* samples_read);
    AudioLevel LastLevel() const { return last_level_; }
    uint32_t LastSequence() const { return last_sequence_; }
    int64_t LastTimestampMs() const { return last_timestamp_ms_; }
    uint32_t LastLossEpoch() const { return last_loss_epoch_; }
    size_t StackFreeBytes() const {
        return task_ == nullptr ? 0 : uxTaskGetStackHighWaterMark(task_);
    }

private:
    static constexpr int kSampleRate = 16000;
    // O INMP441 entrega amostras de 24 bits alinhadas em uma palavra I2S de
    // 32 bits. O pipeline de treino normaliza o WAV com o equivalente a >> 16.
    static constexpr int kI2sToPcmShift = 16;
    static constexpr uint32_t kCaptureStackBytes = 6144;
    struct Frame {
        int16_t samples[320];
        size_t count;
        AudioLevel level;
        uint32_t sequence;
        uint32_t loss_epoch;
        int64_t timestamp_ms;
    };
    static void CaptureEntry(void* context);
    static bool OnOverflow(i2s_chan_handle_t channel, i2s_event_data_t* event, void* context);
    uint32_t LossEpoch();
    void MarkLoss();
    void RunCapture();
    // Only the producer task uses these buffers; keep them off its stack.
    int32_t raw_samples_[320] = {};
    Frame capture_frame_ = {};
    Frame discarded_frame_ = {};
    QueueHandle_t frames_ = nullptr;
    TaskHandle_t task_ = nullptr;
    StaticQueue_t queue_control_;
    uint8_t* queue_storage_ = nullptr;
    uint32_t last_sequence_ = 0;
    int64_t last_timestamp_ms_ = 0;
    uint32_t last_loss_epoch_ = 0;
    portMUX_TYPE loss_mux_ = portMUX_INITIALIZER_UNLOCKED;
    uint32_t loss_epoch_ = 0;
    i2s_chan_handle_t channel_ = nullptr;
    AudioLevel last_level_ = {.rms_dbfs = -120.0f, .peak = 0};
};
