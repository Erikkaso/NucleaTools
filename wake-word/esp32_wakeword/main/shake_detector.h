#pragma once
#include <cstdint>

// Input is a sampled, conditioned motion envelope, not a raw piezo GPIO level.
class ShakeDetector {
public:
    constexpr bool Observe(bool strong, int64_t now) {
        if (last_sample_ >= 0 && (now < last_sample_ || now - last_sample_ > 100)) {
            strong_since_ = quiet_since_ = -1;
        }
        last_sample_ = now;
        if (!strong) {
            strong_since_ = -1;
            if (quiet_since_ < 0) quiet_since_ = now;
            if (now - quiet_since_ >= 250) latched_ = false;
            return false;
        }
        quiet_since_ = -1;
        if (latched_) return false;
        if (strong_since_ < 0) strong_since_ = now;
        if (now - strong_since_ <= 1000) return false;
        latched_ = true;
        return true;
    }
private:
    int64_t last_sample_ = -1;
    int64_t strong_since_ = -1;
    int64_t quiet_since_ = -1;
    bool latched_ = false;
};
