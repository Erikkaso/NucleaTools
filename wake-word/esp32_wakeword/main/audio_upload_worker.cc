#include "audio_upload_worker.h"
#include <cstring>
#include "freertos/task.h"
#include "esp_log.h"
#include "auth_key.h"

esp_err_t AudioUploadWorker::Init() {
    if (jobs_ && results_) return ESP_OK;
    const esp_err_t cancel_result = cancellation_.Init();
    if (cancel_result != ESP_OK) return cancel_result;
    const esp_err_t speaker_result = speaker_.Init();
    if (speaker_result != ESP_OK) return speaker_result;
    jobs_ = xQueueCreate(1, sizeof(Job));
    results_ = xQueueCreate(1, sizeof(Completion));
    if (jobs_ == nullptr || results_ == nullptr ||
        xTaskCreatePinnedToCore(Entry, "audio_upload", 8192, this, 2, nullptr, 0) != pdPASS) {
        if (jobs_) vQueueDelete(jobs_);
        if (results_) vQueueDelete(results_);
        jobs_ = results_ = nullptr;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

esp_err_t AudioUploadWorker::Start(const int16_t* samples, size_t count,
                                  const std::string& url, const std::string& auth_key) {
    if (jobs_ == nullptr || busy_) return ESP_ERR_INVALID_STATE;
    if (!samples || count == 0 || url.size() >= sizeof(Job::url) ||
        (!auth_key.empty() && !ValidAuthKey(auth_key)))
        return ESP_ERR_INVALID_ARG;
    Job job = {};
    job.samples = samples;
    job.count = count;
    std::memcpy(job.url, url.c_str(), url.size() + 1);
    std::memcpy(job.auth_key, auth_key.c_str(), auth_key.size() + 1);
    return Submit(job);
}

esp_err_t AudioUploadWorker::StartCue(RecordingCue cue) {
    Job job = {};
    job.kind = JobKind::kCue;
    job.cue = cue;
    return Submit(job);
}

esp_err_t AudioUploadWorker::Submit(const Job& job) {
    if (jobs_ == nullptr || busy_) return ESP_ERR_INVALID_STATE;
    cancellation_.Reset();
    response_started_ = false;
    interruptible_ = false;
    busy_ = true;
    if (xQueueSend(jobs_, &job, 0) == pdTRUE) return ESP_OK;
    busy_ = false;
    return ESP_FAIL;
}

void AudioUploadWorker::Cancel() {
    if (!busy_) return;
    cancellation_.Cancel();
    response_started_ = false;
    speaker_.RequestStop();
}

bool AudioUploadWorker::Poll(esp_err_t* result) {
    Completion completed;
    if (!results_ || !result || xQueuePeek(results_, &completed, 0) != pdTRUE ||
        completed.kind != JobKind::kUpload) return false;
    if (xQueueReceive(results_, &completed, 0) != pdTRUE) return false;
    // The owner has finished publishing: discard even a flag racing with Cancel().
    if (cancellation_.Cancelled()) response_started_ = false;
    *result = completed.result;
    busy_ = false;
    return true;
}

bool AudioUploadWorker::PollCue(RecordingCue* cue, esp_err_t* result) {
    Completion completed;
    if (!results_ || !result || !cue || xQueuePeek(results_, &completed, 0) != pdTRUE ||
        completed.kind != JobKind::kCue) return false;
    if (xQueueReceive(results_, &completed, 0) != pdTRUE) return false;
    *cue = completed.cue;
    *result = completed.result;
    busy_ = false;
    return true;
}

void AudioUploadWorker::Entry(void* context) {
    auto* self = static_cast<AudioUploadWorker*>(context);
    AudioUploader uploader;
    Job job;
    while (true) {
        if (xQueueReceive(self->jobs_, &job, portMAX_DELAY) == pdTRUE) {
            esp_err_t result;
            if (job.kind == JobKind::kCue) {
                result = PlayRecordingCue(self->speaker_, job.cue);
            } else {
                // The recorder is already closed, so offsfx cannot enter the uploaded WAV.
                const esp_err_t cue_result = PlayRecordingCue(self->speaker_, RecordingCue::kOff);
                if (cue_result != ESP_OK)
                    ESP_LOGW("AUDIO_UPLOAD", "Continuando envio apesar da falha no offsfx");
                self->interruptible_ = true;
                result = job.url[0] && !self->cancellation_.Cancelled()
                    ? uploader.Upload(job.samples, job.count, job.url, &self->speaker_, job.auth_key,
                                      &self->cancellation_, &self->response_started_)
                    : ESP_ERR_INVALID_STATE;
            }
            self->interruptible_ = false;
            const Completion completed = {job.kind, job.cue, result};
            xQueueSend(self->results_, &completed, portMAX_DELAY);
        }
    }
}
