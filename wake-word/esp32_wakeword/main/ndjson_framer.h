#pragma once
#include <cstddef>

// Storage is supplied by the caller so the HTTP task never puts a line on its stack.
class NdjsonFramer {
public:
    constexpr NdjsonFramer(char* storage, size_t capacity) : storage_(storage), capacity_(capacity) {}
    template <typename Consumer>
    constexpr bool Feed(const char* data, size_t size, Consumer consume) {
        if (failed_) return false;
        if (!storage_ || capacity_ < 2) return Fail("invalid_storage");
        for (size_t i = 0; i < size; ++i) {
            const char c = data[i];
            if (c == '\0') return Fail("nul_or_binary_data");
            if (c == '\n') {
                if (used_ && storage_[used_ - 1] == '\r') --used_;
                storage_[used_] = '\0';
                if (!used_) return Fail("empty_line");
                if (!consume(storage_, used_)) return Fail("rejected_event");
                used_ = 0;
            } else {
                if (used_ >= capacity_ - 1) return Fail("line_too_long");
                storage_[used_++] = c;
            }
        }
        return true;
    }
    constexpr bool Finish() const { return !failed_ && used_ == 0; }
    constexpr const char* Error() const { return error_; }
    constexpr size_t BufferedBytes() const { return used_; }
private:
    constexpr bool Fail(const char* reason) { failed_ = true; error_ = reason; return false; }
    char* storage_;
    size_t capacity_;
    size_t used_ = 0;
    bool failed_ = false;
    const char* error_ = "none";
};
