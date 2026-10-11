#include "audio_upload_worker.h"
#include <cstring>
#include "freertos/task.h"

esp_err_t AudioUploadWorker::Init() {
    jobs_ = xQueueCreate(1, sizeof(Job));
    results_ = xQueueCreate(1, sizeof(esp_err_t));
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
                                  const std::string& url) {
    if (jobs_ == nullptr || busy_) return ESP_ERR_INVALID_STATE;
    if (!samples || count == 0 || url.empty() || url.size() >= sizeof(Job::url))
        return ESP_ERR_INVALID_ARG;
    Job job = {};
    job.samples = samples;
    job.count = count;
    std::memcpy(job.url, url.c_str(), url.size() + 1);
    busy_ = true;
    if (xQueueSend(jobs_, &job, 0) == pdTRUE) return ESP_OK;
    busy_ = false;
    return ESP_FAIL;
}

bool AudioUploadWorker::Poll(esp_err_t* result) {
    if (!results_ || !result || xQueueReceive(results_, result, 0) != pdTRUE) return false;
    busy_ = false;
    return true;
}

void AudioUploadWorker::Entry(void* context) {
    auto* self = static_cast<AudioUploadWorker*>(context);
    AudioUploader uploader;
    Job job;
    while (true) {
        if (xQueueReceive(self->jobs_, &job, portMAX_DELAY) == pdTRUE) {
            const esp_err_t result = uploader.Upload(job.samples, job.count, job.url);
            xQueueSend(self->results_, &result, portMAX_DELAY);
        }
    }
}
