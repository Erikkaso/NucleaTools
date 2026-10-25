#include "detection_gate.h"

#include <algorithm>

void DetectionGate::ResetConfirmation() {
    std::fill_n(history_, 3, 0.0f);
    count_ = cursor_ = 0;
}

bool DetectionGate::Accept(float score, int64_t now_ms) {
    history_[cursor_] = score;
    cursor_ = (cursor_ + 1) % 3;
    count_ = std::min<uint8_t>(count_ + 1, 3);
    if (CooldownRemainingMs(now_ms) > 0) {
        return false;
    }
    const bool normal_confirmation = score >= kThreshold && PositiveCount() >= 2;
    uint8_t support = 0;
    for (float previous : history_) support += previous >= kSupportThreshold;
    // High peaks still need temporal evidence; weaker support preserves short spoken wakewords.
    const bool supported_peak = score >= kSupportThreshold && support >= 2 &&
                                RecentMaxScore() >= kHighConfidenceThreshold;
    if (!normal_confirmation && !supported_peak) {
        return false;
    }
    last_detection_ms_ = now_ms;
    return true;
}

uint8_t DetectionGate::PositiveCount() const {
    uint8_t positives = 0;
    for (float result : history_) {
        positives += result >= kThreshold ? 1 : 0;
    }
    return positives;
}

float DetectionGate::RecentMaxScore() const {
    return *std::max_element(history_, history_ + 3);
}

int64_t DetectionGate::CooldownRemainingMs(int64_t now_ms) const {
    return std::max<int64_t>(0, kCooldownMs - (now_ms - last_detection_ms_));
}
