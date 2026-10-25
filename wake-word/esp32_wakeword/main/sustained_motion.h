#pragma once
#include <cstdint>

// Confirms real shaking: `required` consecutive 100 ms buckets, each well above the
// resting pulse rate (slow average of earlier buckets, so a noisy floating pin does
// not count as movement) and at least `min_pulses`. One quiet bucket is tolerated
// (direction change); two in a row reset. Re-arms after 5 non-active buckets.
class SustainedMotion {
public:
    static constexpr int64_t kBucketMs = 100;
    static constexpr float kRatio = 2.5f;
    constexpr SustainedMotion(unsigned required, unsigned min_pulses)
        : required_(required < 1 ? 1 : required), min_pulses_(min_pulses < 1 ? 1 : min_pulses) {}
    // Call with each sample's pulse count; returns true once per confirmed shake.
    constexpr bool Observe(unsigned pulses, int64_t now) {
        if (bucket_start_ < 0) bucket_start_ = now;
        pulses_ += pulses;
        if (now - bucket_start_ < kBucketMs - 1) return false;
        const float count = static_cast<float>(pulses_);
        pulses_ = 0;
        bucket_start_ = now + 1;
        if (baseline_ < 0) baseline_ = count;
        float threshold = kRatio * baseline_;
        if (threshold < static_cast<float>(min_pulses_)) threshold = static_cast<float>(min_pulses_);
        const bool active = count >= threshold;
        baseline_ += (count - baseline_) / (active ? 500.0f : 50.0f);
        if (!active) {
            ++quiet_run_;
            if (quiet_run_ >= 2) active_ = 0;
            if (quiet_run_ >= 5) latched_ = false;
            return false;
        }
        quiet_run_ = 0;
        ++active_;
        if (latched_ || active_ < required_) return false;
        latched_ = true;
        active_ = 0;
        return true;
    }
private:
    unsigned required_, min_pulses_;
    unsigned active_ = 0, quiet_run_ = 0, pulses_ = 0;
    float baseline_ = -1;
    int64_t bucket_start_ = -1;
    bool latched_ = false;
};
