#pragma once
#include <cstddef>
#include <cstdint>

class SpeakerStreamState {
public:
    constexpr bool Start() {
        if (started_) return false;
        started_ = true;
        return true;
    }
    constexpr bool Audio(uint32_t seq, int rate, size_t bytes) {
        if (!started_ || ended_ || seq != next_ || rate != 24000 ||
            !bytes || bytes > 4800 || bytes % 2) return false;
        ++next_;
        return true;
    }
    constexpr bool Ping() const { return started_ && !ended_; }
    constexpr bool End() {
        if (!started_ || ended_ || !next_) return false;
        ended_ = true;
        return true;
    }
    constexpr bool Finished() const { return ended_; }
private:
    bool started_ = false;
    bool ended_ = false;
    uint32_t next_ = 0;
};
