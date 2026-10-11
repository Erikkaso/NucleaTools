#include "visual_state.h"

namespace {
constexpr bool SleepWakeIdleCycle() {
    VisualStateMachine state(30000);
    if (state.State() != VisualState::kSleeping) return false;
    state.Wake();
    if (state.State() != VisualState::kWaking) return false;
    state.TransitionComplete(1200);
    state.Tick(120000);
    if (state.State() != VisualState::kAwake) return false; // HTTP still busy.
    state.Ready(120000);
    state.Tick(149999);
    if (state.State() != VisualState::kAwake) return false;
    state.Tick(150000);
    if (state.State() != VisualState::kClosing) return false;
    state.TransitionComplete(151200);
    return state.State() == VisualState::kSleeping;
}
constexpr bool WakeInterruptsClosing() {
    VisualStateMachine state(1000);
    state.Wake();
    state.TransitionComplete(1200);
    state.Ready(1300);
    state.Tick(2300);
    state.Wake();
    if (state.State() != VisualState::kWaking) return false;
    state.TransitionComplete(2500);
    state.Tick(99999);
    return state.State() == VisualState::kAwake;
}
constexpr bool FastRequestWaitsForOpening() {
    VisualStateMachine state(1000);
    state.Wake();
    state.Ready(100);
    state.Tick(1100);
    if (state.State() != VisualState::kWaking) return false;
    state.TransitionComplete(1200);
    state.Tick(2199);
    if (state.State() != VisualState::kAwake) return false;
    state.Tick(2200);
    return state.State() == VisualState::kClosing;
}
static_assert(SleepWakeIdleCycle(), "Sleep/wake/HTTP busy/idle cycle failed");
static_assert(WakeInterruptsClosing(), "New wake must interrupt closing");
static_assert(FastRequestWaitsForOpening(), "Opening must finish before idle timer");
}
