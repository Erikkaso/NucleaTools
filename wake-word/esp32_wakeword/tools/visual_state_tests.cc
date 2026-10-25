#include "visual_state.h"
#include "shake_detector.h"

namespace {
constexpr bool DeferredSleepWake() {
    VisualStateMachine state(1000);
    state.Wake();
    if (state.Clip() != VisualClip::kSleep) return false;
    state.CycleComplete(100);
    if (state.Clip() != VisualClip::kWake) return false;
    state.Ready(200);
    state.CycleComplete(300);
    if (state.Clip() != VisualClip::kBlink) return false;
    state.CycleComplete(1299);
    if (state.Clip() != VisualClip::kBlink) return false;
    state.CycleComplete(1300);
    if (state.Clip() != VisualClip::kClose) return false;
    state.Wake();
    if (state.Clip() != VisualClip::kClose) return false;
    state.CycleComplete(1400);
    return state.Clip() == VisualClip::kWake;
}
constexpr bool BusyNeverSleeps() {
    VisualStateMachine state(1000);
    state.Wake();
    state.CycleComplete(100);
    state.CycleComplete(200);
    state.CycleComplete(999999);
    return state.Clip() == VisualClip::kBlink;
}
constexpr bool ResponseWeights() {
    unsigned blink = 0, smile = 0, elegant = 0;
    for (unsigned roll = 0; roll < 100; ++roll) {
        VisualStateMachine state(30000);
        state.Wake();
        state.CycleComplete(0);
        state.CycleComplete(100);
        state.Response(roll);
        if (state.Clip() != VisualClip::kBlink) return false;
        state.CycleComplete(200);
        blink += state.Clip() == VisualClip::kBlink;
        smile += state.Clip() == VisualClip::kSmile;
        elegant += state.Clip() == VisualClip::kElegant;
        state.CycleComplete(300);
        if (state.Clip() != VisualClip::kBlink) return false;
    }
    return blink == 45 && smile == 30 && elegant == 25;
}
constexpr bool ShakeSequenceAndReset() {
    VisualStateMachine state(30000);
    state.Wake();
    state.CycleComplete(0);
    state.CycleComplete(100);
    if (!state.Shake(1000) || state.ShakeCount() != 1) return false;
    if (state.Clip() != VisualClip::kBlink) return false;
    state.CycleComplete(1100);
    if (state.Clip() != VisualClip::kDizzy) return false;
    state.CycleComplete(1200);
    if (state.Clip() != VisualClip::kBlink) return false;
    if (!state.Shake(2000)) return false;
    state.CycleComplete(2100);
    if (state.Clip() != VisualClip::kDizzy) return false;
    state.CycleComplete(2200);
    if (state.Clip() != VisualClip::kAngry) return false;
    state.CycleComplete(2300);
    if (state.Clip() != VisualClip::kBlink) return false;
    if (!state.Shake(3000) || state.ShakeCount() != 0) return false;
    state.CycleComplete(3100);
    if (state.Clip() != VisualClip::kDizzy) return false;
    state.CycleComplete(3200);
    if (state.Clip() != VisualClip::kCry) return false;
    state.CycleComplete(3300);
    return state.Clip() == VisualClip::kBlink && state.Shake(4000) && state.ShakeCount() == 1;
}
constexpr bool TimeoutAndQueueBound() {
    VisualStateMachine state(1000);
    if (!state.Shake(0)) return false;
    if (!state.Shake(120000) || state.ShakeCount() != 1) return false;
    state.Shake(120100);
    state.Shake(120200);
    state.Shake(120300);
    const auto count = state.ShakeCount();
    if (state.Shake(120400) || state.ShakeCount() != count) return false;
    return true;
}
constexpr bool NoMidCycleInterruption() {
    VisualStateMachine state(1000);
    state.Wake();
    state.CycleComplete(100);
    state.CycleComplete(200);
    state.Response(99);
    state.CycleComplete(300);
    if (state.Clip() != VisualClip::kElegant) return false;
    state.Shake(400);
    state.Ready(500);
    state.Wake();
    if (state.Clip() != VisualClip::kElegant) return false;
    state.CycleComplete(600);
    return state.Clip() == VisualClip::kDizzy;
}
constexpr bool ShakeRequiresSustainedSamples() {
    ShakeDetector sensor;
    for (int64_t t = 0; t <= 1000; t += 20)
        if (sensor.Observe(true, t)) return false;
    if (!sensor.Observe(true, 1020)) return false;
    for (int64_t t = 1040; t < 3000; t += 20)
        if (sensor.Observe(true, t)) return false;
    for (int64_t t = 3000; t <= 3300; t += 20)
        if (sensor.Observe(false, t)) return false;
    for (int64_t t = 3320; t <= 4320; t += 20)
        if (sensor.Observe(true, t)) return false;
    return sensor.Observe(true, 4340);
}
constexpr bool SensorGapAndShortPulsesDoNotQualify() {
    ShakeDetector sensor;
    sensor.Observe(true, 0);
    if (sensor.Observe(true, 2000)) return false;
    for (int64_t t = 2020; t <= 2900; t += 20)
        if (sensor.Observe(true, t)) return false;
    sensor.Observe(false, 2920);
    for (int64_t t = 2940; t <= 3900; t += 20)
        if (sensor.Observe(true, t)) return false;
    return true;
}
constexpr bool ExpressionReturnsToBlinkBeforeSleep() {
    VisualStateMachine state(1000);
    state.Wake();
    state.CycleComplete(0);
    state.CycleComplete(100);
    state.Ready(100);
    state.Response(99);
    state.CycleComplete(200);
    state.CycleComplete(5000);
    if (state.Clip() != VisualClip::kBlink) return false;
    state.CycleComplete(6000);
    return state.Clip() == VisualClip::kClose;
}
constexpr bool QueuedShakesKeepBlinkSeparators() {
    VisualStateMachine state(1000);
    state.Wake();
    state.CycleComplete(0);
    state.CycleComplete(100);
    if (!state.Shake(1000) || !state.Shake(2000) || !state.Shake(3000)) return false;
    const VisualClip expected[] = {
        VisualClip::kDizzy, VisualClip::kBlink,
        VisualClip::kDizzy, VisualClip::kAngry, VisualClip::kBlink,
        VisualClip::kDizzy, VisualClip::kCry, VisualClip::kBlink,
    };
    for (auto clip : expected) {
        state.CycleComplete(4000);
        if (state.Clip() != clip) return false;
    }
    return true;
}
static_assert(DeferredSleepWake(), "Every transition must wait for the full animation cycle");
static_assert(BusyNeverSleeps(), "HTTP/recording activity must prevent idle sleep");
static_assert(ResponseWeights(), "Response selection must be 45/30/25 and return to blink");
static_assert(ShakeSequenceAndReset(), "Shake sequence must be dizzy, dizzy+angry, dizzy+cry");
static_assert(TimeoutAndQueueBound(), "Two-minute reset and bounded reaction queue failed");
static_assert(NoMidCycleInterruption(), "Wake, reply and shake must not interrupt an expression");
static_assert(ShakeRequiresSustainedSamples(), "Shake requires over one second and quiet rearming");
static_assert(SensorGapAndShortPulsesDoNotQualify(), "Sensor gaps cannot be treated as continuous motion");
static_assert(ExpressionReturnsToBlinkBeforeSleep(), "Expressions must return to blink before closing");
static_assert(QueuedShakesKeepBlinkSeparators(), "Each queued shake must end with blink");
}
