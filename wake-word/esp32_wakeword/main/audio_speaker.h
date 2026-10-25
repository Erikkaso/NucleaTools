#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include "esp_err.h"
#include "sdkconfig.h"
#include "pcm_coalescer.h"
#include "speaker_dsp.h"

#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
#include "driver/i2s_std.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

// One producer (upload worker), one persistent consumer. Never reset a live queue.
class AudioSpeaker {
public:
    esp_err_t Init(int volume_percent = CONFIG_NUCLEA_SPEAKER_VOLUME_PERCENT);
    esp_err_t Begin();
    bool Push(const uint8_t* pcm, size_t bytes);
    esp_err_t Finish();
    esp_err_t Abort();
    void RequestStop() { abort_ = true; }
    bool Playing() const { return playing_.load(); }
private:
    using Frame = PcmCoalescer::Frame;
    static constexpr size_t kFrames = 400;
    static void Entry(void* context);
    void Run();
    bool Write(const void* data, size_t bytes);
    bool Enqueue(const Frame& frame, int64_t deadline);
    i2s_chan_handle_t channel_ = nullptr;
    QueueHandle_t frames_ = nullptr;
    StaticQueue_t queue_control_ = {};
    uint8_t* queue_storage_ = nullptr;
    Frame* frame_ = nullptr;
    PcmCoalescer* coalescer_ = nullptr;
    int16_t* stereo_ = nullptr;
    SpeakerDsp dsp_;  // Consumer-only after Init.
    SemaphoreHandle_t done_ = nullptr;
    TaskHandle_t task_ = nullptr;
    bool session_ = false;  // Producer-only: every Begin consumes exactly one completion acknowledgement.
    int volume_percent_ = CONFIG_NUCLEA_SPEAKER_VOLUME_PERCENT;
    std::atomic<size_t> queued_bytes_{0};
    std::atomic<bool> idle_{true}, abort_{false}, eof_{false}, failed_{false}, playing_{false};
};
#else
class AudioSpeaker {
public:
    esp_err_t Init() { return ESP_OK; }
    void RequestStop() {}
    bool Playing() const { return false; }
};
#endif
