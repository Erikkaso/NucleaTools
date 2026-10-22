#include "recording_window.h"

namespace {
constexpr size_t kRate = 16000;
constexpr size_t kBase = 5 * kRate;
constexpr size_t kExtension = 3 * kRate / 2;
constexpr size_t kMaximum = 12 * kRate;

constexpr bool SilenceStopsAtFiveSeconds() {
    size_t count = 6400;  // Existing 400 ms pre-roll belongs to the WAV duration.
    while (count < kBase) {
        const auto step = AdvanceRecording(count, 512, false, 0, kBase, kExtension, kMaximum);
        count += step.copied;
        if (step.finished) return count == kBase && !step.maximum;
    }
    return false;
}

constexpr bool ActivityLeavesOneAndHalfSeconds() {
    const size_t active_end = 4 * kRate + kRate / 2;
    const auto active = AdvanceRecording(active_end - 512, 512, true, 0,
                                         kBase, kExtension, kMaximum);
    if (active.finished || active.last_activity != active_end) return false;
    const auto quiet = AdvanceRecording(active_end, 2 * kRate, false, active.last_activity,
                                        kBase, kExtension, kMaximum);
    return quiet.finished && !quiet.maximum && quiet.copied == kExtension;
}

constexpr bool ContinuousActivityStopsAtTwelveSeconds() {
    size_t count = 6400;
    size_t last_activity = 0;
    while (count < kMaximum) {
        const auto step = AdvanceRecording(count, 512, true, last_activity,
                                            kBase, kExtension, kMaximum);
        count += step.copied;
        last_activity = step.last_activity;
        if (step.finished) return count == kMaximum && step.maximum;
    }
    return false;
}

static_assert(SilenceStopsAtFiveSeconds(), "Silence must produce exactly a five-second WAV");
static_assert(ActivityLeavesOneAndHalfSeconds(), "Activity must renew the 1.5-second tail");
static_assert(ContinuousActivityStopsAtTwelveSeconds(), "Recording cannot exceed twelve seconds");
static_assert(!AdvanceRecording(16000, 512, false, 0, kBase, kExtension, kMaximum).finished,
              "Early silence cannot stop the five-second base window");
static_assert(AdvanceRecording(kMaximum, 512, true, kMaximum, kBase, kExtension, kMaximum).copied == 0,
              "A full recording must not append past the buffer");
}  // namespace
