#pragma once
#include <cstddef>
#include <cstdint>

class PcmCoalescer {
public:
    struct Frame { uint16_t bytes = 0; uint8_t pcm[480] = {}; };
    template <typename Sink>
    constexpr bool Feed(const uint8_t* data, size_t bytes, Sink sink) {
        if (failed_ || !data || !bytes || bytes % 2) return false;
        for (size_t i = 0; i < bytes; ++i) {
            frame_.pcm[frame_.bytes++] = data[i];
            if (frame_.bytes == sizeof(frame_.pcm)) {
                if (!sink(frame_)) { failed_ = true; return false; }
                frame_.bytes = 0;
            }
        }
        return true;
    }
    template <typename Sink>
    constexpr bool Flush(Sink sink) {
        if (failed_) return false;
        if (frame_.bytes && !sink(frame_)) { failed_ = true; return false; }
        frame_.bytes = 0;
        return true;
    }
    constexpr void Reset() { frame_.bytes = 0; failed_ = false; }
private:
    Frame frame_;
    bool failed_ = false;
};
