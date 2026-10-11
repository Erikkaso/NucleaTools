#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "esp_err.h"

class AudioUploader {
public:
    esp_err_t Upload(const int16_t* samples, size_t sample_count, const std::string& base_url) const;
};
