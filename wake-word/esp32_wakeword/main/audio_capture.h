#pragma once

#include <cstddef>
#include <cstdint>

#include "driver/i2s_std.h"
#include "esp_err.h"

struct AudioLevel {
    float rms_dbfs;
    int16_t peak;
};

class AudioCapture {
public:
    esp_err_t Init();
    esp_err_t ReadPcm16(int16_t* destination, size_t capacity, size_t* samples_read);
    AudioLevel LastLevel() const { return last_level_; }

private:
    static constexpr int kSampleRate = 16000;
    // O INMP441 entrega amostras de 24 bits alinhadas em uma palavra I2S de
    // 32 bits. O pipeline de treino normaliza o WAV com o equivalente a >> 16.
    static constexpr int kI2sToPcmShift = 16;
    i2s_chan_handle_t channel_ = nullptr;
    AudioLevel last_level_ = {.rms_dbfs = -120.0f, .peak = 0};
};
