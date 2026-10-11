#pragma once
#include "audio_uploader.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

class AudioUploadWorker {
public:
    esp_err_t Init();
    esp_err_t Start(const int16_t* samples, size_t count, const std::string& url);
    bool Poll(esp_err_t* result);
    bool Busy() const { return busy_; }
private:
    struct Job { const int16_t* samples; size_t count; char url[256]; };
    static void Entry(void* context);
    QueueHandle_t jobs_ = nullptr;
    QueueHandle_t results_ = nullptr;
    bool busy_ = false;
};
