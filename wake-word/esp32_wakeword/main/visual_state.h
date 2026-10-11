#pragma once
#include <cstdint>

enum class VisualState { kSleeping, kWaking, kAwake, kClosing };

class VisualStateMachine {
public:
    explicit constexpr VisualStateMachine(int64_t idle_ms) : idle_ms_(idle_ms) {}
    constexpr VisualState State() const { return state_; }
    constexpr void Wake() {
        busy_ = true;
        if (state_ == VisualState::kSleeping || state_ == VisualState::kClosing)
            state_ = VisualState::kWaking;
    }
    constexpr void Ready(int64_t now) { busy_ = false; deadline_ = now + idle_ms_; }
    constexpr void Tick(int64_t now) {
        if (state_ == VisualState::kAwake && !busy_ && now >= deadline_)
            state_ = VisualState::kClosing;
    }
    constexpr void TransitionComplete(int64_t now) {
        if (state_ == VisualState::kWaking) {
            state_ = VisualState::kAwake;
            if (!busy_) deadline_ = now + idle_ms_;
        } else if (state_ == VisualState::kClosing) state_ = VisualState::kSleeping;
    }
private:
    VisualState state_ = VisualState::kSleeping;
    bool busy_ = false;
    int64_t deadline_ = 0;
    int64_t idle_ms_;
};
