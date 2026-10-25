#include "knock_detector.h"
#include "piezo_envelope.h"
#include "shake_detector.h"
#include "sustained_motion.h"

namespace {
// Feeds 20 ms samples with a pulse every pulse_ms; returns whether a shake confirmed.
constexpr bool Shake(int64_t hold_ms, int64_t pulse_ms, int64_t duration_ms) {
    PiezoEnvelope envelope(hold_ms);
    ShakeDetector detector;
    bool confirmed = false;
    for (int64_t now = 0; now <= duration_ms + 400; now += 20) {
        const bool pulse = now < duration_ms && now % pulse_ms == 0;
        confirmed |= detector.Observe(envelope.Observe(pulse ? 1 : 0, now), now);
    }
    return confirmed;
}
// Knock times in ms; each listed time is one 20 ms sample with a pulse.
template <int N>
constexpr bool Knocks(const int64_t (&times)[N]) {
    KnockDetector detector(3, 2000);
    bool confirmed = false;
    int next = 0;
    for (int64_t now = 0; now <= 6000; now += 20) {
        const bool pulse = next < N && times[next] == now;
        if (pulse) ++next;
        confirmed |= detector.Observe(pulse, now);
    }
    return confirmed;
}
// Pulses per 20 ms sample at the given rate (per second) for duration_ms, then silence.
constexpr bool Sustained(unsigned per_sample, int64_t duration_ms, int64_t gap_start = -1, int64_t gap_end = -1) {
    SustainedMotion motion(6, 4);
    bool confirmed = false;
    constexpr int64_t kRest = 3000;  // The board sits still before anyone shakes it.
    for (int64_t now = 0; now <= kRest + duration_ms + 1000; now += 20) {
        const int64_t t = now - kRest;
        const bool gap = t >= gap_start && t < gap_end;
        confirmed |= motion.Observe(t >= 0 && t < duration_ms && !gap ? per_sample : 0, now);
    }
    return confirmed;
}
// Steady noise of `rest` pulses/sample for 10 s, then `burst` pulses/sample for burst_ms.
constexpr bool NoisyRest(unsigned rest, unsigned burst, int64_t burst_ms, bool* quiet_ok) {
    SustainedMotion motion(6, 4);
    bool during_rest = false, during_burst = false;
    for (int64_t now = 0; now < 10000 + burst_ms + 600; now += 20) {
        const bool in_burst = now >= 10000 && now < 10000 + burst_ms;
        const bool fired = motion.Observe(in_burst ? burst : rest, now);
        if (now < 10000) during_rest |= fired;
        else during_burst |= fired;
    }
    *quiet_ok = !during_rest;
    return during_burst;
}
constexpr bool NoisyRestIgnored() { bool q = false; NoisyRest(2, 6, 1500, &q); return q; }
constexpr bool BurstOverNoiseFires() { bool q = false; return NoisyRest(2, 6, 1500, &q); }
constexpr bool ShortBurstOverNoiseIgnored() { bool q = false; return !NoisyRest(2, 6, 300, &q); }
constexpr int64_t kThreeKnocks[] = {0, 400, 800};
constexpr int64_t kSlowKnocks[] = {0, 1200, 2400, 3600};
constexpr int64_t kRinging[] = {0, 20, 40, 60, 80, 100};  // One hit ringing for 100 ms.
constexpr int64_t kTwoKnocks[] = {0, 500};
constexpr bool EnvelopeHoldsBetweenPulses() {
    PiezoEnvelope envelope(200);
    return !envelope.Observe(0, 0) && envelope.Observe(3, 20) &&
           envelope.Observe(0, 220) && !envelope.Observe(0, 240);
}
}

static_assert(EnvelopeHoldsBetweenPulses(), "envelope must bridge gaps up to hold_ms");
static_assert(Shake(200, 160, 1500), "steady shaking for 1.5 s must confirm");
static_assert(!Shake(200, 160, 800), "a short shake must not confirm");
static_assert(!Shake(200, 400, 3000), "pulses slower than the hold window must not confirm");
static_assert(!Shake(200, 100000, 100), "a single knock must not confirm");
static_assert(Knocks(kThreeKnocks), "three knocks within 2 s must confirm");
static_assert(!Knocks(kSlowKnocks), "knocks spread beyond the window must not confirm");
static_assert(!Knocks(kRinging), "pulses of one ringing knock count once");
static_assert(!Knocks(kTwoKnocks), "two knocks are not enough");
static_assert(Sustained(1, 1500), "1 pulse/20ms (50/s) for 1.5 s must confirm");
static_assert(!Sustained(1, 400), "shaking under 0.5 s must not confirm");
static_assert(!Sustained(0, 3000), "silence must not confirm");
static_assert(Sustained(2, 1500, 600, 700), "a single quiet bucket is tolerated");
static_assert(NoisyRestIgnored(), "constant pin noise must never fire");
static_assert(BurstOverNoiseFires(), "a 1.5 s burst over the noise floor must fire");
static_assert(ShortBurstOverNoiseIgnored(), "a 0.3 s burst over noise must not fire");
