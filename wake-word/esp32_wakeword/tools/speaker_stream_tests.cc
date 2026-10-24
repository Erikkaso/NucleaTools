#include "ndjson_framer.h"
#include <cstddef>
#include "speaker_stream_state.h"
#include "pcm_coalescer.h"
#include "http_read_budget.h"

constexpr bool AllSplits() {
    constexpr char wire[] = "start\r\naudio\nend\n";
    for (size_t split = 0; split < sizeof(wire); ++split) {
        char storage[16] = {};
        NdjsonFramer framer(storage, sizeof(storage));
        unsigned count = 0;
        auto consume = [&](const char* line, size_t length) {
            const size_t expected[] = {5, 5, 3};
            const char initial[] = {'s', 'a', 'e'};
            if (count >= 3 || length != expected[count] || line[0] != initial[count]) return false;
            ++count;
            return true;
        };
        if (!framer.Feed(wire, split, consume) ||
            !framer.Feed(wire + split, sizeof(wire) - 1 - split, consume) ||
            !framer.Finish() || count != 3) return false;
    }
    return true;
}
constexpr bool BoundsAndFailure() {
    char storage[8] = {};
    auto accept = [](const char*, size_t) { return true; };
    NdjsonFramer truncated(storage, sizeof(storage));
    if (!truncated.Feed("{}", 2, accept) || truncated.Finish()) return false;
    NdjsonFramer overflow(storage, sizeof(storage));
    if (overflow.Feed("12345678", 8, accept) || overflow.Feed("\n", 1, accept)) return false;
    NdjsonFramer rejected(storage, sizeof(storage));
    if (rejected.Feed("{}\n", 3, [](const char*, size_t) { return false; }) || rejected.Finish()) return false;
    NdjsonFramer nul(storage, sizeof(storage));
    return !nul.Feed("{\0}\n", 4, accept);
}
static_assert(AllSplits(), "Reassemble arbitrary HTTP chunks and strip CRLF");
static_assert(BoundsAndFailure(), "Reject overflow, NUL, truncated lines and sink failures");

constexpr bool Protocol() {
    SpeakerStreamState s;
    if (s.Audio(0, 24000, 4800) || s.End() || s.Finished()) return false;
    if (!s.Start() || s.Start() || !s.Ping()) return false;
    if (s.Audio(1, 24000, 4800) || s.Audio(0, 16000, 3200) ||
        s.Audio(0, 24000, 4802) || s.Audio(0, 24000, 3) || s.Audio(0, 24000, 0)) return false;
    if (!s.Audio(0, 24000, 4800) || s.Audio(0, 24000, 4800) || s.Finished()) return false;
    if (!s.Audio(1, 24000, 2) || !s.End() || !s.Finished()) return false;
    return !s.End() && !s.Start() && !s.Audio(2, 24000, 2) && !s.Ping();
}
static_assert(Protocol(), "Validate event order, sequence, rate, PCM bounds and terminal end");

constexpr bool BytewiseAndCapacity() {
    char storage[8] = {};
    NdjsonFramer framer(storage, sizeof(storage));
    constexpr char wire[] = "1234567\n{}\r\n";
    unsigned count = 0;
    auto consume = [&](const char* line, size_t length) {
        ++count;
        return count == 1 ? length == 7 && line[6] == '7' && line[7] == '\0'
                          : length == 2 && line[1] == '}' && line[2] == '\0';
    };
    for (size_t i = 0; i < sizeof(wire) - 1; ++i)
        if (!framer.Feed(wire + i, 1, consume)) return false;
    return framer.Finish() && count == 2;
}
static_assert(BytewiseAndCapacity(), "Bytewise delivery and maximum line length preserve JSON text");

constexpr bool EmptyAndTerminal() {
    char storage[16] = {};
    NdjsonFramer framer(storage, sizeof(storage));
    if (framer.Feed("\n", 1, [](const char*, size_t) { return true; })) return false;
    SpeakerStreamState s;
    if (s.Ping() || !s.Start() || s.End() || s.Finished()) return false;
    if (!s.Audio(0, 24000, 2) || !s.End()) return false;
    auto event = [&](const char*, size_t) { return s.Ping(); };
    NdjsonFramer trailing(storage, sizeof(storage));
    return !trailing.Feed("ping\n", 5, event) && !trailing.Finish();
}
static_assert(EmptyAndTerminal(), "Reject blank lines, empty streams and events after end");

constexpr bool TinyPcmEvents() {
    PcmCoalescer coalescer;
    constexpr uint8_t sample[] = {0x34, 0x12};
    unsigned frames = 0, bytes = 0;
    auto sink = [&](const PcmCoalescer::Frame& frame) {
        ++frames; bytes += frame.bytes;
        for (size_t i = 0; i < frame.bytes; ++i)
            if (frame.pcm[i] != sample[i % 2]) return false;
        return true;
    };
    for (unsigned i = 0; i < 400; ++i)
        if (!coalescer.Feed(sample, 2, sink)) return false;
    if (frames != 1 || bytes != 480) return false;
    if (!coalescer.Flush(sink) || frames != 2 || bytes != 800) return false;
    return coalescer.Flush(sink) && frames == 2;
}
constexpr bool PcmBoundariesAndAbort() {
    uint8_t data[482] = {};
    for (size_t i = 0; i < 482; ++i) data[i] = i % 251;
    for (size_t split = 2; split < 482; split += 2) {
        PcmCoalescer coalescer;
        unsigned bytes = 0;
        auto sink = [&](const PcmCoalescer::Frame& frame) {
            for (size_t i = 0; i < frame.bytes; ++i)
                if (frame.pcm[i] != data[bytes++]) return false;
            return true;
        };
        if (!coalescer.Feed(data, split, sink) ||
            !coalescer.Feed(data + split, 482 - split, sink) || bytes != 480 ||
            !coalescer.Flush(sink) || bytes != 482) return false;
        if (!coalescer.Feed(data, 2, sink)) return false;
        coalescer.Reset();
        if (!coalescer.Flush(sink) || bytes != 482) return false;
    }
    PcmCoalescer failed;
    auto reject = [](const PcmCoalescer::Frame&) { return false; };
    return !failed.Feed(data, 480, reject) && !failed.Flush(reject);
}
static_assert(TinyPcmEvents(), "Tiny PCM events share full queue frames; EOF flushes the tail once");
static_assert(PcmBoundariesAndAbort(), "Preserve PCM across event boundaries and discard partial PCM on reset");

constexpr bool SlowTrickleBudget() {
    HttpReadBudget budget(240000000, 0);
    for (int64_t now = 0; now < 220000000; now += 900000) {
        if (budget.Expired(now)) return false;
        const int64_t left_ms = (220000000 - now) / 1000;
        const int expected = left_ms > 1000 ? 1000 : static_cast<int>(left_ms);
        // DATA/ping activity does not renew the progress deadline.
        if (budget.TimeoutMs(now) != expected) return false;
    }
    if (!budget.Expired(220000000) || budget.TimeoutMs(220000000) != 1) return false;
    HttpReadBudget active(240000000, 0);
    active.AudioProgress(10000000);
    if (active.Expired(99999000) || active.TimeoutMs(99999000) != 1 || !active.Expired(100000000)) return false;
    active.AudioProgress(239000000);
    return !active.Expired(239999000) && active.TimeoutMs(239999000) == 1 && active.Expired(240000000);
}
static_assert(SlowTrickleBudget(), "Internal transport timeouts shrink to absolute/audio deadlines despite byte trickles");

constexpr bool FramerDiagnostics() {
    char storage[8] = {};
    auto accept = [](const char*, size_t) { return true; };
    NdjsonFramer binary(storage, sizeof(storage));
    if (binary.Feed("\x1f\x8b\x08\0", 4, accept)) return false;
    if (binary.Error()[0] != 'n' || binary.Error()[1] != 'u') return false;
    NdjsonFramer blank(storage, sizeof(storage));
    if (blank.Feed("\n", 1, accept) || blank.Error()[0] != 'e') return false;
    NdjsonFramer long_line(storage, sizeof(storage));
    return !long_line.Feed("12345678", 8, accept) && long_line.Error()[0] == 'l';
}
static_assert(FramerDiagnostics(), "Distinguish binary/compressed, blank and overlong stream data");
