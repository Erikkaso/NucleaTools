#pragma once
#include <cstdint>

// Turns piezo pulse counts, sampled every 20 ms, into the motion envelope that
// ShakeDetector expects: shaking yields pulses at each knock or direction
// change, so the envelope stays strong while pulses keep arriving within hold_ms.
class PiezoEnvelope {
public:
    explicit constexpr PiezoEnvelope(int64_t hold_ms) : hold_ms_(hold_ms) {}
    constexpr bool Observe(unsigned pulses, int64_t now) {
        if (pulses) last_pulse_ = now;
        return last_pulse_ >= 0 && now - last_pulse_ <= hold_ms_;
    }
private:
    int64_t hold_ms_;
    int64_t last_pulse_ = -1;
};
