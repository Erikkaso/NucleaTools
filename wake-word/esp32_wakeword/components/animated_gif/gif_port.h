#pragma once
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
inline unsigned long millis() { return esp_timer_get_time() / 1000; }
inline void delay(unsigned long ms) { vTaskDelay(pdMS_TO_TICKS(ms)); }
