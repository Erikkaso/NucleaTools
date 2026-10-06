#include "status_led.h"

#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace {
constexpr gpio_num_t kLedPin = GPIO_NUM_48;
}

esp_err_t StatusLed::Init() {
    led_strip_config_t strip_config = {
        .strip_gpio_num = kLedPin,
        .max_leds = 1,
        .led_pixel_format = LED_PIXEL_FORMAT_GRB,
        .led_model = LED_MODEL_WS2812,
        .flags = {},
    };
    led_strip_rmt_config_t rmt_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 64,
        .flags = {},
    };
    init_error_ = led_strip_new_rmt_device(&strip_config, &rmt_config, &strip_);
    if (init_error_ == ESP_OK) {
        init_error_ = SetOff();
    }
    return init_error_;
}

esp_err_t StatusLed::SetColor(uint8_t red, uint8_t green, uint8_t blue) {
    if (init_error_ != ESP_OK || strip_ == nullptr) {
        return init_error_;
    }
    ESP_RETURN_ON_ERROR(led_strip_set_pixel(strip_, 0, red, green, blue), "STATUS_LED", "set pixel");
    return led_strip_refresh(strip_);
}

esp_err_t StatusLed::SetOff() {
    green_ = false;
    if (init_error_ != ESP_OK || strip_ == nullptr) {
        return init_error_;
    }
    ESP_RETURN_ON_ERROR(led_strip_clear(strip_), "STATUS_LED", "clear");
    return led_strip_refresh(strip_);
}

esp_err_t StatusLed::RunSelfTest() {
    ESP_RETURN_ON_ERROR(SetColor(32, 0, 0), "STATUS_LED", "red");
    vTaskDelay(pdMS_TO_TICKS(180));
    ESP_RETURN_ON_ERROR(SetColor(0, 32, 0), "STATUS_LED", "green");
    vTaskDelay(pdMS_TO_TICKS(180));
    ESP_RETURN_ON_ERROR(SetColor(0, 0, 32), "STATUS_LED", "blue");
    vTaskDelay(pdMS_TO_TICKS(180));
    return SetOff();
}

esp_err_t StatusLed::ToggleDetected() {
    green_ = !green_;
    return green_ ? SetColor(0, 48, 0) : SetOff();
}
