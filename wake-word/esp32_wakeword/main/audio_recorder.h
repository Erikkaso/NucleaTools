#pragma once

#include <cstddef>
#include <cstdint>

#include "esp_err.h"

enum class RecordingResult {
    kContinue,
    kSilence,
    kMaximumDuration,
    kBufferFull,
};

class AudioRecorder {
public:
    ~AudioRecorder();
    esp_err_t Init();
    esp_err_t Start(const int16_t* pre_roll, size_t pre_roll_samples, int64_t now_ms);
    RecordingResult Append(const int16_t* samples, size_t count, float rms_dbfs, int64_t now_ms);
    void Reset();

    bool IsRecording() const { return recording_; }
    const int16_t* Data() const { return samples_; }
    size_t SampleCount() const { return sample_count_; }

private:
    static constexpr size_t kSampleRate = 16000;
    int16_t* samples_ = nullptr;
    size_t capacity_ = 0;
    size_t sample_count_ = 0;
    size_t last_activity_sample_ = 0;
    bool recording_ = false;
};
