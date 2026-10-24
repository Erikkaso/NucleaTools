#include "upload_cancellation.h"
#include "lwip/sockets.h"

esp_err_t UploadCancellation::Init() {
    if (!mutex_) mutex_ = xSemaphoreCreateMutex();
    return mutex_ ? ESP_OK : ESP_ERR_NO_MEM;
}

void UploadCancellation::Reset() {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    socket_ = -1;
    cancelled_ = false;
    xSemaphoreGive(mutex_);
}

void UploadCancellation::Cancel() {
    cancelled_ = true;
    xSemaphoreTake(mutex_, portMAX_DELAY);
    if (socket_ >= 0) shutdown(socket_, SHUT_RDWR);
    xSemaphoreGive(mutex_);
}

void UploadCancellation::PublishSocket(int socket) {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    socket_ = socket;
    if (cancelled_ && socket_ >= 0) shutdown(socket_, SHUT_RDWR);
    xSemaphoreGive(mutex_);
}

void UploadCancellation::DetachSocket() {
    xSemaphoreTake(mutex_, portMAX_DELAY);
    socket_ = -1;
    xSemaphoreGive(mutex_);
}
