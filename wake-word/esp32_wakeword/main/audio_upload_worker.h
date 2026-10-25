#pragma once
#include "audio_uploader.h"
#include "recording_cues.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

class AudioUploadWorker {
public:
    esp_err_t Init();
    esp_err_t Start(const int16_t* samples, size_t count, const std::string& url,
                    const std::string& auth_key = {});
    esp_err_t StartCue(RecordingCue cue);
    bool PollCue(RecordingCue* cue, esp_err_t* result);
    bool Poll(esp_err_t* result);
    bool Busy() const { return busy_; }
    bool Interruptible() const { return busy_ && interruptible_.load() && !cancellation_.Cancelled(); }
    void Cancel();
    bool Playing() const { return speaker_.Playing(); }
    bool TakeResponseStarted() { return response_started_.exchange(false) && !cancellation_.Cancelled(); }
private:
    enum class JobKind { kUpload, kCue };
    struct Job {
        JobKind kind = JobKind::kUpload;
        RecordingCue cue = RecordingCue::kOff;
        const int16_t* samples = nullptr;
        size_t count = 0;
        char url[256] = {};
        char auth_key[129] = {};
    };
    struct Completion { JobKind kind; RecordingCue cue; esp_err_t result; };
    esp_err_t Submit(const Job& job);
    static void Entry(void* context);
    QueueHandle_t jobs_ = nullptr;
    QueueHandle_t results_ = nullptr;
    bool busy_ = false;
    std::atomic<bool> interruptible_{false};
    std::atomic<bool> response_started_{false};
    UploadCancellation cancellation_;
    AudioSpeaker speaker_;
};
