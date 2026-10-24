#pragma once
#include <atomic>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

// One HTTP owner; other tasks may only signal cancellation and shut down its socket.
class UploadCancellation {
public:
    esp_err_t Init();
    void Reset();  // Only after the previous worker completion has been consumed.
    void Cancel();
    bool Cancelled() const { return cancelled_.load(); }
    void PublishSocket(int socket);
    void DetachSocket();
private:
    std::atomic<bool> cancelled_{false};
    SemaphoreHandle_t mutex_ = nullptr;
    int socket_ = -1;
};
