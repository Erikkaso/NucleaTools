#include "auth_key.h"
#include <cassert>
#include <string>

static_assert(ValidAuthKey("0123456789abcdef0123456789abcdef"));
static_assert(!ValidAuthKey(""));
static_assert(!ValidAuthKey("0123456789abcdef0123456789abcde"));
static_assert(!ValidAuthKey("0123456789abcdef0123456789abcdef "));
static_assert(!ValidAuthKey("0123456789abcdef0123456789abcdef\r\n"));
static_assert(!ValidAuthKey("0123456789abcdef0123456789abcdef\x80"));
static_assert(!ValidAuthKey(std::string_view("0123456789abcdef0123456789abcdef\0", 33)));

int main() {
    assert(!ValidAuthKey(""));
    assert(!ValidAuthKey(std::string(31, 'a')));
    assert(ValidAuthKey(std::string(32, 'a')));
    assert(ValidAuthKey(std::string(128, 'a')));
    assert(!ValidAuthKey(std::string(129, 'a')));
    assert(!ValidAuthKey(std::string(32, 'a') + "\r\nX-Evil: injected"));
    assert(!ValidAuthKey(std::string(32, 'a') + " "));
    assert(!ValidAuthKey(std::string(32, 'a') + char(0x80)));
    assert(!ValidAuthKey(std::string(32, 'a') + '\0'));
}
