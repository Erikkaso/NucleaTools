#pragma once
#include <cstdint>

constexpr int64_t DisplayFrameDeadline(int64_t started, int64_t rendered,
                                       int delay_ms, bool last_frame) {
    const int64_t hold = delay_ms < 10 ? 10 : delay_ms;
    if (last_frame) return rendered + hold;
    const int64_t nominal = started + hold;
    return nominal > rendered ? nominal : rendered + 1;
}
