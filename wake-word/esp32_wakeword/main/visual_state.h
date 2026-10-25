#pragma once
#include <cstdint>

enum class VisualState { kSleeping, kWaking, kAwake, kClosing };
enum class VisualClip { kSleep, kWake, kBlink, kSmile, kElegant, kDizzy, kAngry, kCry, kClose,
                        kLoadingIn, kLoading, kLoadingOut };

class VisualStateMachine {
public:
    explicit constexpr VisualStateMachine(int64_t idle_ms) : idle_ms_(idle_ms) {}
    constexpr VisualState State() const { return state_; }
    constexpr VisualClip Clip() const {
        if (state_ == VisualState::kSleeping) return VisualClip::kSleep;
        if (state_ == VisualState::kWaking) return VisualClip::kWake;
        if (state_ == VisualState::kClosing) return VisualClip::kClose;
        return expression_;
    }
    constexpr void Wake() {
        busy_ = true;
        wake_requested_ = true;
        response_pending_ = false;
        if (state_ == VisualState::kSleeping) {
            state_ = VisualState::kWaking;
            wake_requested_ = false;
        }
    }
    // A request reached the model: after kLoadingDelayMs, idle -> loadingtrans -> loading loop
    // until reply or Ready().
    static constexpr int64_t kLoadingDelayMs = 1500;
    constexpr void Loading(int64_t now) { thinking_ = true; loading_at_ = now + kLoadingDelayMs; }
    // True when idle should be cut short to start loadingtrans; the renderer then restarts.
    constexpr bool LoadingDue(int64_t now) const {
        return thinking_ && state_ == VisualState::kAwake && expression_ == VisualClip::kBlink &&
               now >= loading_at_;
    }
    constexpr void Ready(int64_t now) { busy_ = false; thinking_ = false; deadline_ = now + idle_ms_; }
    constexpr void Response(unsigned roll) {
        response_ = roll % 100 < 45 ? VisualClip::kBlink :
                    roll % 100 < 75 ? VisualClip::kSmile : VisualClip::kElegant;
        response_pending_ = true;
        thinking_ = false;
        wake_requested_ = true;
    }
    constexpr unsigned ShakeCount() const { return shake_count_; }
    constexpr bool Shake(int64_t now) {
        if (last_shake_ >= 0 && now - last_shake_ >= 120000) shake_count_ = 0;
        const unsigned stage = shake_count_ + 1;
        const bool reacting = state_ == VisualState::kAwake &&
            (expression_ == VisualClip::kDizzy || expression_ == VisualClip::kAngry ||
             expression_ == VisualClip::kCry);
        const unsigned needed = stage == 1 ? 2 : 3;
        if (reaction_size_ + needed > kReactionCapacity) return false;
        reactions_[(reaction_head_ + reaction_size_++) % kReactionCapacity] = VisualClip::kDizzy;
        if (stage > 1)
            reactions_[(reaction_head_ + reaction_size_++) % kReactionCapacity] =
                stage == 2 ? VisualClip::kAngry : VisualClip::kCry;
        reactions_[(reaction_head_ + reaction_size_++) % kReactionCapacity] = VisualClip::kBlink;
        shake_count_ = stage == 3 ? 0 : stage;
        last_shake_ = now;
        wake_requested_ = true;
        if (!busy_) deadline_ = now + idle_ms_;
        if (!reacting) {
            // Abrupt: drop whatever plays (sleep, wake, idle...) and jump to the first reaction.
            state_ = VisualState::kAwake;
            wake_requested_ = false;
            expression_ = reactions_[reaction_head_];
            reaction_head_ = (reaction_head_ + 1) % kReactionCapacity;
            --reaction_size_;
            interrupted_ = true;
        }
        return true;
    }
    // True once after Shake() replaced the current clip; the renderer must restart its loop.
    constexpr bool TakeInterrupt() { const bool r = interrupted_; interrupted_ = false; return r; }
    // Only the renderer calls this, after displaying the last frame for its full delay.
    constexpr void CycleComplete(int64_t now) {
        if (state_ == VisualState::kSleeping || state_ == VisualState::kClosing) {
            state_ = wake_requested_ ? VisualState::kWaking : VisualState::kSleeping;
            wake_requested_ = false;
        } else if (state_ == VisualState::kWaking) {
            state_ = VisualState::kAwake;
            if (!busy_) deadline_ = now + idle_ms_;
            NextExpression(now, false);
        } else {
            wake_requested_ = false;
            NextExpression(now, expression_ == VisualClip::kBlink);
        }
    }
private:
    constexpr void NextExpression(int64_t now, bool allow_sleep) {
        const bool loading = expression_ == VisualClip::kLoadingIn || expression_ == VisualClip::kLoading;
        expression_ = VisualClip::kBlink;
        if (reaction_size_) {
            expression_ = reactions_[reaction_head_];
            reaction_head_ = (reaction_head_ + 1) % kReactionCapacity;
            --reaction_size_;
        } else if (loading && !thinking_) {
            expression_ = VisualClip::kLoadingOut;  // loading -> idle before the reply expression
        } else if (response_pending_) {
            expression_ = response_;
            response_pending_ = false;
        } else if (thinking_ && (loading || now >= loading_at_)) {
            expression_ = loading ? VisualClip::kLoading : VisualClip::kLoadingIn;
        } else if (allow_sleep && !busy_ && now >= deadline_) {
            state_ = VisualState::kClosing;
        }
    }
    static constexpr unsigned kReactionCapacity = 8;
    VisualState state_ = VisualState::kSleeping;
    VisualClip expression_ = VisualClip::kBlink;
    VisualClip response_ = VisualClip::kBlink;
    VisualClip reactions_[kReactionCapacity] = {};
    unsigned reaction_head_ = 0;
    unsigned reaction_size_ = 0;
    unsigned shake_count_ = 0;
    int64_t last_shake_ = -1;
    bool wake_requested_ = false;
    bool response_pending_ = false;
    bool busy_ = false;
    bool interrupted_ = false;
    bool thinking_ = false;
    int64_t loading_at_ = 0;
    int64_t deadline_ = 0;
    int64_t idle_ms_;
};
