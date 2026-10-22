#pragma once

#include <algorithm>
#include <cstddef>

struct RecordingStep {
    size_t copied;
    size_t last_activity;
    bool finished;
    bool maximum;
};

constexpr RecordingStep AdvanceRecording(size_t recorded, size_t requested, bool active,
                                          size_t last_activity, size_t base_samples,
                                          size_t extension_samples, size_t maximum_samples) {
    if (recorded >= maximum_samples) return {0, last_activity, true, true};
    const size_t chunk_end = recorded + std::min(requested, maximum_samples - recorded);
    if (active) last_activity = chunk_end;
    const size_t deadline = std::min(maximum_samples,
                                     std::max(base_samples, last_activity + extension_samples));
    const size_t available = deadline > recorded ? deadline - recorded : 0;
    const size_t copied = std::min(requested, available);
    const size_t end = recorded + copied;
    return {copied, last_activity, end >= deadline, end >= maximum_samples};
}
