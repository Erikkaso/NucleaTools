#include "portal_button.h"

namespace {
constexpr bool HoldTriggersOnceUntilReleased() {
    PortalButtonHold button;
    if (button.Update(true, 0) || button.Update(true, 2999)) return false;
    if (!button.Update(true, 3000)) return false;
    if (button.Update(true, 6000) || button.Update(false, 6001)) return false;
    if (button.Update(true, 7000)) return false;
    return button.Update(true, 10000);
}

constexpr bool ShortPressesDoNotAccumulate() {
    PortalButtonHold button;
    if (button.Update(true, 0) || button.Update(true, 2000)) return false;
    if (button.Update(false, 2100) || button.Update(true, 3000)) return false;
    if (button.Update(true, 5999)) return false;
    return button.Update(true, 6000);
}

constexpr bool ReleasedButtonNeverTriggers() {
    PortalButtonHold button;
    return !button.Update(false, 0) && !button.Update(false, 3000) &&
           !button.Update(false, 100000);
}
}

static_assert(HoldTriggersOnceUntilReleased(), "BOOT must trigger once per 3-second hold");
static_assert(ShortPressesDoNotAccumulate(), "Short presses and bounce must reset hold time");
static_assert(ReleasedButtonNeverTriggers(), "Released BOOT must not open the portal");
