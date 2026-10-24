#pragma once
#include "sdkconfig.h"
#ifdef CONFIG_NUCLEA_SPEAKER_ENABLED
#include "audio_speaker.h"
#include "ndjson_framer.h"
#include "speaker_stream_state.h"

class SpeakerResponse {
public:
    explicit SpeakerResponse(AudioSpeaker& speaker);
    ~SpeakerResponse();
    SpeakerResponse(const SpeakerResponse&) = delete;
    SpeakerResponse& operator=(const SpeakerResponse&) = delete;
    bool Ready() const { return line_ && pcm_; }
    bool Feed(const char* data, size_t size);
    bool Complete() const { return framer_.Finish() && state_.Finished(); }
    size_t AudioEvents() const { return audio_events_; }
    const char* FramingError() const { return framer_.Error(); }
    size_t BufferedBytes() const { return framer_.BufferedBytes(); }
private:
    bool Line(const char* data, size_t size);
    AudioSpeaker& speaker_;
    char* line_;
    uint8_t* pcm_;
    NdjsonFramer framer_;
    SpeakerStreamState state_;
    size_t audio_events_ = 0;
};
#endif
