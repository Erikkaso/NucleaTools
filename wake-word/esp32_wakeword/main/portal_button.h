#pragma once

#include <cstdint>

class PortalButtonHold {
public:
    constexpr bool Update(bool pressed, int64_t now_ms) {
        if (!pressed) {
            pressed_ = false;
            fired_ = false;
            return false;
        }
        if (!pressed_) {
            pressed_ = true;
            pressed_at_ms_ = now_ms;
        }
        if (!fired_ && now_ms - pressed_at_ms_ >= 3000) {
            fired_ = true;
            return true;
        }
        return false;
    }

private:
    bool pressed_ = false;
    bool fired_ = false;
    int64_t pressed_at_ms_ = 0;
};
