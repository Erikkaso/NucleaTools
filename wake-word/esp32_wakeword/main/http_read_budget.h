#pragma once
#include <cstdint>

class HttpReadBudget {
public:
    constexpr HttpReadBudget(int64_t absolute_us, int64_t now_us)
        : absolute_us_(absolute_us), progress_us_(now_us + 220000000) {}
    constexpr int TimeoutMs(int64_t now_us) const {
        const int64_t remaining_us = Deadline() - now_us;
        if (remaining_us < 1000) return 1;
        return remaining_us > 1000000 ? 1000 : static_cast<int>(remaining_us / 1000);
    }
    constexpr bool Expired(int64_t now_us) const { return now_us >= Deadline(); }
    constexpr void AudioProgress(int64_t now_us) { progress_us_ = now_us + 90000000; }
private:
    constexpr int64_t Deadline() const { return absolute_us_ < progress_us_ ? absolute_us_ : progress_us_; }
    int64_t absolute_us_;
    int64_t progress_us_;
};
