#pragma once
#include <string_view>

constexpr bool ValidAuthKey(std::string_view key) {
    if (key.size() < 32 || key.size() > 128) return false;
    for (unsigned char c : key) if (c < 33 || c > 126) return false;
    return true;
}
