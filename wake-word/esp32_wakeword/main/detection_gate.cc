#include "detection_gate.h"

#include <algorithm>

void DetectionGate::ResetConfirmation() {
    std::fill_n(history_, 3, false);
    count_ = cursor_ = 0;
}

bool DetectionGate::Accept(float score, int64_t now_ms) {
    history_[cursor_] = score >= kThreshold;
    cursor_ = (cursor_ + 1) % 3;
    count_ = std::min<uint8_t>(count_ + 1, 3);
    if (CooldownRemainingMs(now_ms) > 0) {
        return false;
    }
    if (score < kHighConfidenceThreshold && PositiveCount() < 2) {
        return false;
    }
    last_detection_ms_ = now_ms;
    return true;
}

uint8_t DetectionGate::PositiveCount() const {
    uint8_t positives = 0;
    for (bool result : history_) {
        positives += result ? 1 : 0;
    }
    return positives;
}

int64_t DetectionGate::CooldownRemainingMs(int64_t now_ms) const {
    return std::max<int64_t>(0, kCooldownMs - (now_ms - last_detection_ms_));
}
