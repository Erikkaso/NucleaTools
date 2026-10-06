#pragma once

#include "esp_err.h"
#include "led_strip.h"

class StatusLed {
public:
    esp_err_t Init();
    esp_err_t RunSelfTest();
    esp_err_t SetOff();
    esp_err_t ToggleDetected();
    bool IsGreen() const { return green_; }

private:
    esp_err_t SetColor(uint8_t red, uint8_t green, uint8_t blue);
    led_strip_handle_t strip_ = nullptr;
    esp_err_t init_error_ = ESP_ERR_INVALID_STATE;
    bool green_ = false;
};
