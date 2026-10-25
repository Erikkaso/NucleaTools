#pragma once

#include <cstddef>
#include <atomic>
#include <cstdint>
#include <string>

#include "esp_err.h"
#include "audio_speaker.h"
#include "upload_cancellation.h"

class AudioUploader {
public:
    esp_err_t Upload(const int16_t* samples, size_t sample_count, const std::string& base_url,
                     AudioSpeaker* speaker = nullptr, const std::string& auth_key = {},
                     UploadCancellation* cancellation = nullptr,
                     std::atomic<bool>* response_started = nullptr) const;
};
