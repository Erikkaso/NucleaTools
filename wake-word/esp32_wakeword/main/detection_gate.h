#pragma once

#include <cstdint>

class DetectionGate {
public:
    bool Accept(float score, int64_t now_ms);
    uint8_t PositiveCount() const;
    int64_t CooldownRemainingMs(int64_t now_ms) const;

private:
    static constexpr float kThreshold = 0.85f;
    static constexpr float kHighConfidenceThreshold = 0.98f;
    static constexpr int64_t kCooldownMs = 2000;
    bool history_[3] = {};
    uint8_t count_ = 0;
    uint8_t cursor_ = 0;
    int64_t last_detection_ms_ = -kCooldownMs;
};
