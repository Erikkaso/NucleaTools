#pragma once

#include <cstdint>

#include "esp_err.h"

namespace tflite { class MicroInterpreter; }

class WakewordDetector {
public:
    esp_err_t Init();
    esp_err_t Infer(const int8_t* features, float* score);
    bool IsReady() const { return ready_; }
    float InputScale() const { return input_scale_; }
    int InputZeroPoint() const { return input_zero_point_; }
    int LastInputMin() const { return last_input_min_; }
    int LastInputMax() const { return last_input_max_; }
    int LastBackgroundOutput() const { return last_background_output_; }
    int LastWakewordOutput() const { return last_wakeword_output_; }

private:
    tflite::MicroInterpreter* interpreter_ = nullptr;
    bool ready_ = false;
    float input_scale_ = 0.0f;
    int input_zero_point_ = 0;
    int last_input_min_ = 0;
    int last_input_max_ = 0;
    int last_background_output_ = 0;
    int last_wakeword_output_ = 0;
};
