#include "audio_recorder.h"

#include <algorithm>
#include <cstring>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "sdkconfig.h"

namespace {
constexpr const char* kTag = "AUDIO_RECORDER";
}

AudioRecorder::~AudioRecorder() {
    heap_caps_free(samples_);
}

esp_err_t AudioRecorder::Init() {
    if (!esp_psram_is_initialized()) {
        ESP_LOGE(kTag, "PSRAM nao inicializada");
        return ESP_ERR_INVALID_STATE;
    }
    capacity_ = (kSampleRate * CONFIG_NUCLEA_MAX_RECORDING_MS) / 1000;
    samples_ = static_cast<int16_t*>(
        heap_caps_malloc(capacity_ * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (samples_ == nullptr) return ESP_ERR_NO_MEM;
    ESP_LOGI(kTag, "Buffer PSRAM pronto: %u bytes",
             static_cast<unsigned>(capacity_ * sizeof(int16_t)));
    return ESP_OK;
}

esp_err_t AudioRecorder::Start(const int16_t* pre_roll, size_t pre_roll_samples, int64_t now_ms) {
    if (samples_ == nullptr || pre_roll == nullptr) return ESP_ERR_INVALID_STATE;
    sample_count_ = std::min(pre_roll_samples, capacity_);
    std::memcpy(samples_, pre_roll + (pre_roll_samples - sample_count_),
                sample_count_ * sizeof(int16_t));
    started_at_ms_ = now_ms;
    last_speech_at_ms_ = now_ms;
    recording_ = true;
    return ESP_OK;
}

RecordingResult AudioRecorder::Append(const int16_t* samples, size_t count, float rms_dbfs,
                                      int64_t now_ms) {
    if (!recording_ || samples == nullptr) return RecordingResult::kBufferFull;
    const size_t available = capacity_ - sample_count_;
    const size_t copied = std::min(count, available);
    std::memcpy(samples_ + sample_count_, samples, copied * sizeof(int16_t));
    sample_count_ += copied;

    if (rms_dbfs >= static_cast<float>(CONFIG_NUCLEA_SILENCE_DBFS)) {
        last_speech_at_ms_ = now_ms;
    }
    if (copied < count || sample_count_ == capacity_) {
        recording_ = false;
        return RecordingResult::kBufferFull;
    }
    if (now_ms - started_at_ms_ >= CONFIG_NUCLEA_MAX_RECORDING_MS) {
        recording_ = false;
        return RecordingResult::kMaximumDuration;
    }
    if (now_ms - last_speech_at_ms_ >= CONFIG_NUCLEA_SILENCE_MS) {
        recording_ = false;
        return RecordingResult::kSilence;
    }
    return RecordingResult::kContinue;
}

void AudioRecorder::Reset() {
    recording_ = false;
    sample_count_ = 0;
}
