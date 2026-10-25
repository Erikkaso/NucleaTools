#pragma once
#include <cstdint>

// Confirms a reaction after `required` separate knocks within `window_ms`.
// For weak piezo wiring where each knock yields only one or two pulses, too
// few for the continuous ShakeDetector. Pulses closer than kGapMs belong to
// the same knock (the disc rings briefly after each hit).
class KnockDetector {
public:
    static constexpr unsigned kMaxKnocks = 8;
    static constexpr int64_t kGapMs = 150;
    constexpr KnockDetector(unsigned required, int64_t window_ms)
        : required_(required < 1 ? 1 : required > kMaxKnocks ? kMaxKnocks : required),
          window_ms_(window_ms) {}
    constexpr unsigned Knocks() const { return size_; }
    // Returns true once when the knock that completes the pattern arrives.
    constexpr bool Observe(bool pulse, int64_t now) {
        // Forget knocks that fell out of the window.
        unsigned kept = 0;
        for (unsigned i = 0; i < size_; ++i)
            if (now - knocks_[i] <= window_ms_) knocks_[kept++] = knocks_[i];
        size_ = kept;
        if (!pulse || (last_pulse_ >= 0 && now - last_pulse_ < kGapMs)) {
            if (pulse) last_pulse_ = now;
            return false;
        }
        last_pulse_ = now;
        knocks_[size_++] = now;
        if (size_ < required_) return false;
        size_ = 0;
        return true;
    }
private:
    unsigned required_;
    int64_t window_ms_;
    int64_t knocks_[kMaxKnocks] = {};
    unsigned size_ = 0;
    int64_t last_pulse_ = -1;
};
